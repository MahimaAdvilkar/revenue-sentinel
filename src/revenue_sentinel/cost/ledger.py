"""Recording what a call actually cost, and reconciling the reservation.

The governor reserves a **worst case** before the call; this records the **actual** after
it. The difference is released rather than kept, so an over-reservation does not
permanently consume budget it never spent.

**A `$0.00` entry is written for every call, including fixture-mode ones.** Zero really
was spent, so the figure is true rather than a placeholder -- and an absent row would be
ambiguous between "free" and "not recorded", which is exactly the ambiguity a ledger
exists to remove.

Tool calls against SIMULATED adapters bill nothing and get a zero entry for the same
reason.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.ids import new_id
from revenue_sentinel.cost.pricing import PRICING_VERSION, cost_of
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import BudgetScope, CostType

ZERO = Decimal("0.000000")


def record_model_cost(
    session: Session,
    *,
    run_id: UUID,
    model_call: obs_orm.ModelCall,
    occurred_at: datetime,
) -> obs_orm.CostEntry:
    """Price a completed model call from its **real** token counts.

    Nothing here estimates. In fixture mode the row honestly reports zero tokens, so the
    entry is `0.000000` -- see ADR-0013 and ADR-0020.
    """
    amount = cost_of(
        model_id=model_call.model_id,
        input_tokens=model_call.input_tokens,
        output_tokens=model_call.output_tokens,
        cache_read_tokens=model_call.cache_read_tokens,
        cache_write_tokens=model_call.cache_write_tokens,
    )
    return _write(
        session,
        run_id=run_id,
        model_call_id=model_call.id,
        tool_call_id=None,
        cost_type=CostType.MODEL_INFERENCE,
        amount=amount,
        occurred_at=occurred_at,
    )


def record_tool_cost(
    session: Session, *, run_id: UUID, tool_call_id: UUID, occurred_at: datetime
) -> obs_orm.CostEntry:
    """Always `0.000000` in v1: every adapter is SIMULATED and bills nothing."""
    return _write(
        session,
        run_id=run_id,
        model_call_id=None,
        tool_call_id=tool_call_id,
        cost_type=CostType.TOOL_INVOCATION,
        amount=ZERO,
        occurred_at=occurred_at,
    )


def _write(
    session: Session,
    *,
    run_id: UUID,
    model_call_id: UUID | None,
    tool_call_id: UUID | None,
    cost_type: CostType,
    amount: Decimal,
    occurred_at: datetime,
) -> obs_orm.CostEntry:
    entry = obs_orm.CostEntry(
        id=new_id(),
        run_id=run_id,
        model_call_id=model_call_id,
        tool_call_id=tool_call_id,
        cost_type=cost_type,
        amount_usd=amount,
        pricing_version=PRICING_VERSION,
        recorded_at=occurred_at,
    )
    session.add(entry)
    session.flush()
    _consume(session, run_id=run_id, amount=amount)
    return entry


def _consume(session: Session, *, run_id: UUID, amount: Decimal) -> None:
    """Add the actual spend to every applicable budget.

    Only the **actual** figure lands here. The worst-case reservation was never written,
    so there is nothing to release: reserving in memory and consuming in the database
    keeps `SUM(cost_entries) == budgets.consumed_usd` exactly true, which is the
    reconciliation a test asserts.
    """
    if amount == ZERO:
        return

    session.execute(
        sa.update(obs_orm.Budget)
        .where(
            sa.or_(
                sa.and_(
                    obs_orm.Budget.scope == BudgetScope.RUN,
                    obs_orm.Budget.scope_ref == str(run_id),
                ),
                obs_orm.Budget.scope == BudgetScope.GLOBAL,
            )
        )
        .values(consumed_usd=obs_orm.Budget.consumed_usd + amount)
    )
    session.flush()


def run_total(session: Session, run_id: UUID) -> Decimal:
    """What one run cost. The figure the CLI prints and the demo asserts is `$0.00`."""
    value = session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(obs_orm.CostEntry.amount_usd), 0)).where(
            obs_orm.CostEntry.run_id == run_id
        )
    )
    return Decimal(value or 0).quantize(Decimal("0.000001"))
