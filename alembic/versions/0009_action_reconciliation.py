"""Let an `INDETERMINATE` action carry the attestation that resolved it.

ADR-0017 made execution at-least-once with an explicit unknown, and ADR-0025 makes
resolving that unknown a recorded human act. The audit trail already holds the history;
these columns hold the answer -- who attested the outcome, when, and on what basis --
so "is this resolved" is a column read rather than an event replay.

The CHECK is the part worth reading. A reconciliation is all three fields or none: a row
naming an actor with no evidence would be an attestation with no stated basis, which is
exactly what the mandatory-evidence rule exists to prevent. Enforcing it in the schema
means the rule survives code that writes the row directly.

Nullable and additive, so the upgrade is safe on existing rows: every action recorded
before this migration is simply unreconciled, which is true.

Downgrade drops the columns and **loses the attestations**, which is why it refuses when
any row holds one rather than discarding a human's recorded finding silently -- the same
posture migration 0007 takes toward sub-cent spend.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECONCILIATION_CHECK: str = (
    "(reconciled_by IS NULL) = (reconciled_at IS NULL) "
    "AND (reconciled_by IS NULL) = (reconciliation_evidence IS NULL)"
)


def upgrade() -> None:
    op.add_column("action_records", sa.Column("reconciled_by", sa.String(128), nullable=True))
    op.add_column(
        "action_records",
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("action_records", sa.Column("reconciliation_evidence", sa.Text(), nullable=True))
    op.create_check_constraint(
        "reconciliation_is_complete_or_absent", "action_records", RECONCILIATION_CHECK
    )


def downgrade() -> None:
    reconciled = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM action_records WHERE reconciled_by IS NOT NULL"))
        .scalar_one()
    )
    if reconciled:
        raise RuntimeError(
            f"{reconciled} action record(s) carry a human reconciliation. Downgrading "
            f"would discard an operator's attestation about whether a real effect "
            f"occurred. Export them first."
        )

    op.drop_constraint("reconciliation_is_complete_or_absent", "action_records", type_="check")
    for column in ("reconciliation_evidence", "reconciled_at", "reconciled_by"):
        op.drop_column("action_records", column)
