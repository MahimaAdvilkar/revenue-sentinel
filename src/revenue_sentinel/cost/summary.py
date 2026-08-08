"""Cost totals for a run, at microdollar precision.

Displayed figures keep six decimal places deliberately. Rounding a governance figure to
cents is how `$0.000150` of real spend becomes `$0.00` and stops being auditable -- the
same reasoning that gives `cost_entries.amount_usd` its `NUMERIC(12, 6)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import BudgetScope, CostType

MICRO = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class BudgetView:
    scope: BudgetScope
    scope_ref: str | None
    limit_usd: Decimal
    consumed_usd: Decimal
    hard_stop: bool

    @property
    def remaining_usd(self) -> Decimal:
        return (self.limit_usd - self.consumed_usd).quantize(MICRO)


@dataclass(frozen=True, slots=True)
class CostSummary:
    model_cost: Decimal
    tool_cost: Decimal
    model_calls: int
    tool_calls: int
    pricing_versions: tuple[str, ...]
    budgets: tuple[BudgetView, ...] = field(default_factory=tuple)

    @property
    def total_cost(self) -> Decimal:
        return (self.model_cost + self.tool_cost).quantize(MICRO)


def _sum(session: Session, run_id: UUID, cost_type: CostType) -> Decimal:
    value = session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(obs_orm.CostEntry.amount_usd), 0)).where(
            obs_orm.CostEntry.run_id == run_id, obs_orm.CostEntry.cost_type == cost_type
        )
    )
    return Decimal(value or 0).quantize(MICRO)


def summarise_run(session: Session, *, run_id: UUID, incident_ref: str) -> CostSummary:
    def count(model: type[obs_orm.ModelCall] | type[obs_orm.ToolCall], column: object) -> int:
        value = session.scalar(
            sa.select(sa.func.count()).select_from(model).where(column == run_id)  # type: ignore[arg-type]
        )
        return int(value or 0)

    versions = session.scalars(
        sa.select(obs_orm.CostEntry.pricing_version)
        .where(obs_orm.CostEntry.run_id == run_id)
        .distinct()
    ).all()

    budgets = session.scalars(
        sa.select(obs_orm.Budget).where(
            sa.or_(
                sa.and_(
                    obs_orm.Budget.scope == BudgetScope.RUN,
                    obs_orm.Budget.scope_ref == str(run_id),
                ),
                sa.and_(
                    obs_orm.Budget.scope == BudgetScope.INCIDENT,
                    obs_orm.Budget.scope_ref == incident_ref,
                ),
                obs_orm.Budget.scope == BudgetScope.GLOBAL,
            )
        )
    ).all()

    return CostSummary(
        model_cost=_sum(session, run_id, CostType.MODEL_INFERENCE),
        tool_cost=_sum(session, run_id, CostType.TOOL_INVOCATION),
        model_calls=count(obs_orm.ModelCall, obs_orm.ModelCall.run_id),
        tool_calls=count(obs_orm.ToolCall, obs_orm.ToolCall.run_id),
        pricing_versions=tuple(sorted(versions)),
        budgets=tuple(
            BudgetView(
                scope=b.scope,
                scope_ref=b.scope_ref,
                limit_usd=b.limit_usd,
                consumed_usd=b.consumed_usd,
                hard_stop=b.hard_stop,
            )
            for b in budgets
        ),
    )
