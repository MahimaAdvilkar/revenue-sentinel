"""Make "every action traces to its authorisation" a schema guarantee.

`action_records.authorized_by` has been an unconstrained UUID since the baseline, while
the table's own docstring claimed every action traces to the policy decision or approval
that permitted it. A claim like that belongs in the schema. It becomes a real foreign key
to `policy_evaluations`, with `ON DELETE RESTRICT` -- deleting the decision that
authorised an executed action should be hard, not cascading.

`approval_request_id` is added alongside it, nullable and only set for actions that
needed a person. `NULL` therefore means "Tier 1, auto-approved", which lets a query
separate auto-approved work from approved work without re-deriving tiers.

`action_status` gains `indeterminate`: a row claimed as `executing` and found still
`executing` on a later attempt means the process died between claiming the effect and
recording its outcome. Retrying might duplicate a real effect; marking it failed would
hide one. It is recorded as unknown instead (ADR-0017).

**Downgrade** drops the constraints and the column, and refuses if any row is
`indeterminate` -- there is no honest narrower value to map it onto, and rewriting an
unknown into a definite status to make a migration succeed is exactly the kind of quiet
data corruption the audit trail exists to prevent.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTION_STATUS_VALUES = ("pending", "executing", "succeeded", "failed", "skipped")
_INDETERMINATE = "indeterminate"


def upgrade() -> None:
    op.execute(sa.text(f"ALTER TYPE action_status ADD VALUE IF NOT EXISTS '{_INDETERMINATE}'"))

    # Session 5 drafted a target and dropped it on persistence. Harmless while nothing
    # executed; not once something does -- the executor acts on it and the idempotency
    # key is computed from it. Existing rows get the sentinel rather than a guess.
    op.add_column("interventions", sa.Column("target_ref", sa.String(255), nullable=True))
    op.execute(
        sa.text(
            "UPDATE interventions SET target_ref = :unknown WHERE target_ref IS NULL"
        ).bindparams(unknown="unknown:pre-0006")
    )
    op.alter_column("interventions", "target_ref", nullable=False)

    op.add_column("action_records", sa.Column("approval_request_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_action_records_approval_request_id_approval_requests"),
        "action_records",
        "approval_requests",
        ["approval_request_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_action_records_authorized_by_policy_evaluations"),
        "action_records",
        "policy_evaluations",
        ["authorized_by"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    indeterminate = (
        op.get_bind()
        .execute(
            sa.text("SELECT count(*) FROM action_records WHERE status::text = :status").bindparams(
                status=_INDETERMINATE
            )
        )
        .scalar_one()
    )
    if indeterminate:
        raise RuntimeError(
            f"{indeterminate} action_records row(s) are '{_INDETERMINATE}'. Downgrading "
            f"would have to rewrite an unknown outcome as a definite one. Reconcile them "
            f"first; this migration will not invent an answer."
        )

    op.drop_constraint(
        op.f("fk_action_records_authorized_by_policy_evaluations"),
        "action_records",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_action_records_approval_request_id_approval_requests"),
        "action_records",
        type_="foreignkey",
    )
    op.drop_column("action_records", "approval_request_id")
    op.drop_column("interventions", "target_ref")

    # PostgreSQL cannot drop an enum value, so the type is rebuilt without it.
    op.execute(sa.text("ALTER TYPE action_status RENAME TO action_status_old"))
    sa.Enum(*_ACTION_STATUS_VALUES, name="action_status").create(op.get_bind())
    op.execute(
        sa.text(
            "ALTER TABLE action_records ALTER COLUMN status TYPE action_status "
            "USING status::text::action_status"
        )
    )
    op.execute(sa.text("DROP TYPE action_status_old"))
