"""Let budgets hold the same precision as the costs charged against them.

`cost_entries.amount_usd` is `NUMERIC(12, 6)` because a single Haiku call can cost a
small fraction of a cent -- rounding per call to cents would show real spend as $0.00.

`budgets.limit_usd` and `consumed_usd` were `NUMERIC(14, 2)`, inherited from the money
vocabulary used for pipeline figures where cents are the right granularity. Against
microdollar costs that is wrong in both directions: a limit finer than a cent cannot be
expressed, and accumulating `0.000150` into a two-decimal column silently discards it.
A budget that cannot see the spend charged against it is not a budget.

Found by a test that set a limit one microdollar below a reservation and watched the
call be admitted, because the limit had rounded up to the next cent.

Downgrade re-quantizes to two places, which **loses sub-cent consumption**. It refuses
rather than truncating silently when any row would lose value.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ("limit_usd", "consumed_usd"):
        op.alter_column(
            "budgets",
            column,
            existing_type=sa.Numeric(14, 2),
            type_=sa.Numeric(12, 6),
            existing_nullable=False,
        )


def downgrade() -> None:
    lossy = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM budgets "
                "WHERE limit_usd <> round(limit_usd, 2) "
                "   OR consumed_usd <> round(consumed_usd, 2)"
            )
        )
        .scalar_one()
    )
    if lossy:
        raise RuntimeError(
            f"{lossy} budget row(s) hold sub-cent values that two decimal places cannot "
            f"represent. Downgrading would discard real spend. Reconcile them first."
        )

    for column in ("limit_usd", "consumed_usd"):
        op.alter_column(
            "budgets",
            column,
            existing_type=sa.Numeric(12, 6),
            type_=sa.Numeric(14, 2),
            existing_nullable=False,
        )
