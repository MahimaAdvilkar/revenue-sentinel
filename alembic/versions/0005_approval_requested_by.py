"""Give the approval requester a real column, and approvals a human-typeable reference.

Session 5 stored the requesting actor inside `decision_note` as the string
`requested_by=<actor>` and parsed it back out, because the column did not exist and
adding one was not that session's business. It worked and it was tested, but it put an
**authorisation-relevant value in a free-text field** -- any later write to
`decision_note` would silently destroy the only thing standing between an actor and
approving their own request.

This migration makes it a real, typed, `NOT NULL` column.

`approval_ref` (`APR-001`) arrives at the same time, allocated from a sequence exactly as
incident references are. A human approving something at a CLI needs something they can
type; a UUID is not that.

**Backfill.** Rows whose `decision_note` matches the old pattern give up their actor.
Anything else -- there should be none outside a developer's database -- gets the sentinel
`unknown:pre-0005`, which is deliberately not a plausible actor name: it should look wrong
in a query result rather than blend in.

**Downgrade** writes the actor back into `decision_note` where that field is free, and
**raises** where it is not. Neither value can be dropped silently, so the migration
refuses to choose which one to lose -- the same posture as 0004.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPROVAL_REF_SEQUENCE = "approval_ref_seq"
UNKNOWN_REQUESTER = "unknown:pre-0005"
_LEGACY_PATTERN = "^requested_by=(.*)$"


def upgrade() -> None:
    op.execute(sa.text(f"CREATE SEQUENCE IF NOT EXISTS {APPROVAL_REF_SEQUENCE} START WITH 1"))

    op.add_column("approval_requests", sa.Column("requested_by", sa.String(255), nullable=True))
    op.add_column("approval_requests", sa.Column("approval_ref", sa.String(16), nullable=True))

    # Recover the actor from the Session 5 workaround, then clear the field it squatted in.
    op.execute(
        sa.text(
            "UPDATE approval_requests "
            "SET requested_by = substring(decision_note from :pattern) "
            "WHERE decision_note ~ :pattern"
        ).bindparams(pattern=_LEGACY_PATTERN)
    )
    op.execute(
        sa.text(
            "UPDATE approval_requests SET decision_note = NULL WHERE decision_note ~ :pattern"
        ).bindparams(pattern=_LEGACY_PATTERN)
    )
    op.execute(
        sa.text(
            "UPDATE approval_requests SET requested_by = :unknown WHERE requested_by IS NULL"
        ).bindparams(unknown=UNKNOWN_REQUESTER)
    )

    # Existing rows predate references; number them by creation order so the sequence and
    # the data agree afterwards.
    op.execute(
        sa.text(
            # S608 is suppressed below: the only interpolated value is this module's
            # own sequence-name constant, never caller input.
            "UPDATE approval_requests SET approval_ref = 'APR-' || "  # noqa: S608
            f"lpad(nextval('{APPROVAL_REF_SEQUENCE}')::text, 3, '0') "
            "WHERE approval_ref IS NULL"
        )
    )

    op.alter_column("approval_requests", "requested_by", nullable=False)
    op.alter_column("approval_requests", "approval_ref", nullable=False)
    # A single UNIQUE index, which is what `unique=True, index=True` on the model
    # renders as. A separate constraint *and* index would satisfy neither `alembic
    # check` nor a reader wondering why the reference is indexed twice.
    op.create_index(
        op.f("ix_approval_requests_approval_ref"),
        "approval_requests",
        ["approval_ref"],
        unique=True,
    )


def downgrade() -> None:
    # A row with both a real note and a requester cannot represent both in one field.
    # Fail rather than pick.
    conflicting = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM approval_requests "
                "WHERE decision_note IS NOT NULL AND requested_by <> :unknown"
            ).bindparams(unknown=UNKNOWN_REQUESTER)
        )
        .scalar_one()
    )
    if conflicting:
        raise RuntimeError(
            f"{conflicting} approval_requests row(s) hold both a decision note and a "
            f"requester. Downgrading would have to discard one of them. Resolve the "
            f"rows first; this migration will not choose for you."
        )

    op.execute(
        sa.text(
            "UPDATE approval_requests SET decision_note = 'requested_by=' || requested_by "
            "WHERE requested_by <> :unknown"
        ).bindparams(unknown=UNKNOWN_REQUESTER)
    )

    op.drop_index(op.f("ix_approval_requests_approval_ref"), table_name="approval_requests")
    op.drop_column("approval_requests", "approval_ref")
    op.drop_column("approval_requests", "requested_by")
    op.execute(sa.text(f"DROP SEQUENCE IF EXISTS {APPROVAL_REF_SEQUENCE}"))
