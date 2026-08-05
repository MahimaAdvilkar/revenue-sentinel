"""Mark replayed model calls.

`model_calls.is_replay` is `True` when a response came from a fixture rather than from
the API. It mirrors the `is_simulated` convention on the GTM mirror: provenance is a
property of the row, not a convention someone has to remember.

Why the column exists rather than simply not writing a row in fixture mode:
`agent_decisions.model_call_id` is how the system proves which agents are LLM-backed
and which are deterministic -- `WHERE model_call_id IS NULL` is the Session 8
`no_llm_arithmetic` check. Omitting rows offline would make that check vacuous.
Writing rows with invented token counts would fabricate data. So the row is written
with **zero tokens, because zero were consumed**, `stop_reason = 'fixture_replay'`,
and this flag set.

See ADR-0013.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_calls",
        sa.Column("is_replay", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("model_calls", "is_replay")
