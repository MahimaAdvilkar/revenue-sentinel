"""Give evaluation attempts a total, insertion-ordered sequence.

`evaluation_runs` is append-only (ADR-0021): a later passing attempt must never erase the
record of an earlier failure. That guarantee is only useful if the attempts can be put
back in order, and until now they could not be.

`started_at` is supplied by the caller and, in fixture mode, is the frozen
`EVALUATION_TIMESTAMP` -- so every attempt of the golden run carries the *same* value.
`created_at` defaults to `now()`, which in PostgreSQL is the **transaction** timestamp, so
two attempts recorded in one transaction tie there too. Ordering by either produced an
arbitrary order between tied rows: the history screen could show the failure above or
below the later pass, differently on each request.

An identity column is monotonic per insert regardless of transaction or clock, so it
gives the history a total order that means what a reader assumes it means. Postgres
backfills existing rows in physical order when the column is added, which is the best
available reconstruction and is only approximate for rows that already exist -- newly
recorded attempts are exact.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_runs",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
    )
    op.create_unique_constraint("uq_evaluation_runs_seq", "evaluation_runs", ["seq"])


def downgrade() -> None:
    op.drop_constraint("uq_evaluation_runs_seq", "evaluation_runs", type_="unique")
    op.drop_column("evaluation_runs", "seq")
