"""Let an intervention record an action the system may not perform.

`interventions.action_type` and `action_records.action_type` shared one enum. That was
fine while every proposal was also executable, and wrong as soon as the policy layer
became real: a proposal the engine **denies** still has to be persisted, or the refusal
leaves no row and "what did it want to do, and what stopped it?" becomes unanswerable.

So the two columns get two types, which is what they always were semantically:

* `proposed_action` -- what a strategy agent may *propose*. Wider.
* `action_type` -- what the system may *execute*. Unchanged, and deliberately narrow,
  so a prohibited action has no representation in the execution tables at all.

Downgrade recreates the narrow type on `interventions`. It will **fail loudly** if any
row holds a value the narrow type lacks -- which is correct: silently rewriting a
recorded refusal into some permitted action would corrupt the audit trail to make a
migration succeed.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROPOSED_ACTION_VALUES = (
    "crm_task",
    "email_draft",
    "crm_field_update",
    "slack_approval_request",
    "send_email_direct",
    "record_delete",
)

_proposed_action = sa.Enum(*_PROPOSED_ACTION_VALUES, name="proposed_action")


def upgrade() -> None:
    _proposed_action.create(op.get_bind(), checkfirst=False)
    op.alter_column(
        "interventions",
        "action_type",
        existing_type=sa.Enum(name="action_type"),
        type_=_proposed_action,
        postgresql_using="action_type::text::proposed_action",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "interventions",
        "action_type",
        existing_type=_proposed_action,
        type_=sa.Enum(name="action_type"),
        # Raises if a row holds `send_email_direct` or `record_delete`. That is the
        # intended behaviour: those rows are records of refusals, and there is no
        # honest narrow value to map them onto.
        postgresql_using="action_type::text::action_type",
        existing_nullable=False,
    )
    _proposed_action.drop(op.get_bind(), checkfirst=False)
