"""The Cost Governor: may this call proceed?

**Checked before the spend, not after.** A limit noticed after it is exceeded has already
been exceeded -- that is reporting, not enforcement (ADR-0019).

Two kinds of ceiling, both pre-call:

* **Monetary.** Every applicable budget scope must pass. `RUN`, `INCIDENT`, and `GLOBAL`
  are an **AND**, not a precedence order: a call comfortably inside its run budget can
  still be the one that breaks the monthly ceiling. The refusal names the scope that
  failed, because "over budget" without saying which budget is not actionable.
* **Non-monetary.** Model-call and tool-call counts per run, from
  `docs/cost-governance.md` §8. A run that makes forty tool calls is broken whether or
  not the calls were free.

**This is not the policy layer, and a budget refusal is not a policy decision.** Policy
answers *may this happen*; cost answers *can we afford it*. Recording a budget refusal in
`policy_evaluations` would claim a rule refused it when arithmetic did. The two gates run
in order -- policy first, so a denied action is refused for the right reason even when the
budget is also exhausted.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.logging import get_logger
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import BudgetScope
from revenue_sentinel.mcp.errors import ToolErrorCode, ToolFailureError

logger = get_logger(__name__)

MAX_MODEL_CALLS_PER_RUN = 12
MAX_TOOL_CALLS_PER_RUN = 30
"""`docs/cost-governance.md` §8. Non-monetary ceilings exist because "cheap" and
"bounded" are different properties, and a runaway loop of free calls is still a runaway
loop."""


@dataclass(frozen=True, slots=True)
class BudgetRefusal:
    """Which budget refused, and by how much."""

    scope: BudgetScope
    scope_ref: str | None
    limit_usd: Decimal
    consumed_usd: Decimal
    requested_usd: Decimal

    def message(self) -> str:
        return (
            f"{self.scope.value} budget"
            + (f" for {self.scope_ref}" if self.scope_ref else "")
            + f" would be exceeded: {self.consumed_usd} spent + {self.requested_usd} "
            f"reserved > {self.limit_usd} limit."
        )


class CostGovernor:
    """Consulted before every model call and every tool call."""

    def __init__(self, session: Session, *, run_id: UUID, incident_ref: str) -> None:
        self._session = session
        self._run_id = run_id
        self._incident_ref = incident_ref

    # -- monetary ---------------------------------------------------------------
    def check_affordable(self, amount_usd: Decimal) -> BudgetRefusal | None:
        """Every applicable scope, most restrictive wins. `None` means proceed.

        Returns rather than raises so the caller decides what a refusal means -- a
        `hard_stop=false` budget logs and continues, and that is not the governor's
        judgement to make.
        """
        for budget in self._applicable_budgets():
            if budget.consumed_usd + amount_usd > budget.limit_usd:
                refusal = BudgetRefusal(
                    scope=budget.scope,
                    scope_ref=budget.scope_ref,
                    limit_usd=budget.limit_usd,
                    consumed_usd=budget.consumed_usd,
                    requested_usd=amount_usd,
                )
                if not budget.hard_stop:
                    logger.warning("budget_soft_breach", detail=refusal.message())
                    continue
                return refusal
        return None

    @staticmethod
    def overshoot_bound(concurrent_runs: int, worst_case_reservation: Decimal) -> Decimal:
        """How far a hard `GLOBAL` budget can be exceeded by racing admissions (ADR-0026).

        Admission reads `consumed_usd` and the caller proceeds on it; consumption itself
        is race-free (`UPDATE ... SET consumed = consumed + :amount`). So with `N` runs
        admitting concurrently, each may be admitted against a figure omitting at most
        `N-1` other in-flight reservations:

            (concurrent_runs - 1) * worst_case_reservation

        **One run overshoots by exactly zero**, which is the guarantee serialization
        within a run actually provides -- and the reason this is a bounded limitation
        rather than an unbounded one.

        This is a *bound*, not a measurement: no concurrent run has ever happened here.
        """
        if concurrent_runs < 1:
            raise ValueError(f"concurrent_runs must be >= 1, got {concurrent_runs}")
        if worst_case_reservation < 0:
            raise ValueError("worst_case_reservation cannot be negative")
        return (Decimal(concurrent_runs - 1) * worst_case_reservation).quantize(Decimal("0.000001"))

    def reserve_or_raise(self, amount_usd: Decimal) -> None:
        """Raise `BUDGET_EXCEEDED` if any hard budget cannot absorb the worst case."""
        refusal = self.check_affordable(amount_usd)
        if refusal is not None:
            raise ToolFailureError(
                ToolErrorCode.BUDGET_EXCEEDED,
                refusal.message(),
                detail={
                    "scope": refusal.scope.value,
                    "limit_usd": str(refusal.limit_usd),
                    "consumed_usd": str(refusal.consumed_usd),
                    "reserved_usd": str(refusal.requested_usd),
                },
            )

    def _applicable_budgets(self) -> list[obs_orm.Budget]:
        """The run's, the incident's, and the global one -- whichever exist.

        A missing budget is *not* an implicit limit of zero. Budgets are opt-in; a
        deployment with none configured is unbudgeted, which is a deliberate state
        rather than an accidentally blocked one.
        """
        return list(
            self._session.scalars(
                sa.select(obs_orm.Budget).where(
                    sa.or_(
                        sa.and_(
                            obs_orm.Budget.scope == BudgetScope.RUN,
                            obs_orm.Budget.scope_ref == str(self._run_id),
                        ),
                        sa.and_(
                            obs_orm.Budget.scope == BudgetScope.INCIDENT,
                            obs_orm.Budget.scope_ref == self._incident_ref,
                        ),
                        obs_orm.Budget.scope == BudgetScope.GLOBAL,
                    )
                )
            ).all()
        )

    # -- non-monetary -----------------------------------------------------------
    def check_call_ceilings(self) -> None:
        """Refuse a run that has made too many calls, free or not."""
        models = self._count(obs_orm.ModelCall, obs_orm.ModelCall.run_id)
        if models >= MAX_MODEL_CALLS_PER_RUN:
            raise ToolFailureError(
                ToolErrorCode.BUDGET_EXCEEDED,
                f"run has made {models} model calls; the ceiling is "
                f"{MAX_MODEL_CALLS_PER_RUN}. Halting rather than looping.",
                detail={"ceiling": "model_calls", "count": str(models)},
            )

        tools = self._count(obs_orm.ToolCall, obs_orm.ToolCall.run_id)
        if tools >= MAX_TOOL_CALLS_PER_RUN:
            raise ToolFailureError(
                ToolErrorCode.BUDGET_EXCEEDED,
                f"run has made {tools} tool calls; the ceiling is "
                f"{MAX_TOOL_CALLS_PER_RUN}. Halting rather than looping.",
                detail={"ceiling": "tool_calls", "count": str(tools)},
            )

    def _count(
        self,
        model: type[obs_orm.ModelCall] | type[obs_orm.ToolCall],
        column: sa.orm.InstrumentedAttribute[UUID],
    ) -> int:
        value = self._session.scalar(
            sa.select(sa.func.count()).select_from(model).where(column == self._run_id)
        )
        return int(value or 0)
