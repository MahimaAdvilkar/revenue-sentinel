"""Incident reference sequence, and one incident per signal.

Two additions Session 2 needs:

**`incident_ref_seq`** allocates `INC-001`, `INC-002`, ... Using `count(*) + 1`
instead would be a race under any concurrency, and it would pass every
single-threaded test. The sequence is created explicitly here rather than declared
in `Base.metadata`, because Alembic's autogenerate does not compare standalone
sequences -- so it is migration-managed, and `alembic check` stays clean.

Note that sequence allocation is **not** transactional: a rolled-back insert burns
a number. `incidents/service.py` therefore allocates only after deduplication has
already decided the insert will happen.

**`UNIQUE (signal_id)` on `incidents`** makes the ERD's "one signal opens at most
one incident" true, and gives replay safety a third independent boundary beneath
raw-event and signal deduplication.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INCIDENT_REF_SEQUENCE = "incident_ref_seq"


def upgrade() -> None:
    op.execute(sa.text(f"CREATE SEQUENCE IF NOT EXISTS {INCIDENT_REF_SEQUENCE} START WITH 1"))
    op.create_unique_constraint(op.f("uq_incidents_signal_id"), "incidents", ["signal_id"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_incidents_signal_id"), "incidents", type_="unique")
    op.execute(sa.text(f"DROP SEQUENCE IF EXISTS {INCIDENT_REF_SEQUENCE}"))
