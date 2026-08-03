"""Declarative base, naming conventions, and the column vocabulary.

Two things are centralised here so thirty tables cannot drift apart:

* **A constraint naming convention.** Without it PostgreSQL invents names, and an
  Alembic downgrade cannot reliably drop what it did not name. Every index, unique
  constraint, check, foreign key, and primary key gets a predictable identifier.
* **Column type helpers.** Money is always `NUMERIC(14, 2)`, timestamps are always
  `timestamptz`, JSON is always `JSONB`. A one-off `Float` column for money would be
  a silent correctness bug, so the correct type is the convenient one.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Annotated

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from revenue_sentinel.core.types import JSONValue

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every table."""

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


def pg_enum[E: PyEnum](enum_cls: type[E], name: str) -> sa.Enum:
    """A native PostgreSQL enum storing member *values*, not member names.

    SQLAlchemy defaults to storing the Python member *name* (`MID_MARKET`), which
    would put screaming snake case in the database and diverge from every fixture
    and every document. `values_callable` stores `mid_market` instead.
    """
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda members: [member.value for member in members],
    )


# ---------------------------------------------------------------------------
# Column vocabulary
# ---------------------------------------------------------------------------
uuid_pk = Annotated[
    uuid.UUID,
    mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4),
]
uuid_fk = Annotated[uuid.UUID, mapped_column(sa.Uuid)]

money = Annotated[Decimal, mapped_column(sa.Numeric(14, 2))]
"""`NUMERIC(14, 2)`. Never `Float` -- see `docs/data-model.md` §1."""

cost_amount = Annotated[Decimal, mapped_column(sa.Numeric(12, 6))]
"""`NUMERIC(12, 6)` for sub-cent model spend."""

probability = Annotated[Decimal, mapped_column(sa.Numeric(5, 4))]
score = Annotated[Decimal, mapped_column(sa.Numeric(6, 2))]

timestamp_tz = Annotated[datetime, mapped_column(sa.DateTime(timezone=True))]
calendar_date = Annotated[date, mapped_column(sa.Date)]

short_text = Annotated[str, mapped_column(sa.String(255))]
long_text = Annotated[str, mapped_column(sa.Text)]
digest = Annotated[str, mapped_column(sa.String(64))]
trace_id_col = Annotated[str, mapped_column(sa.String(32))]
span_id_col = Annotated[str, mapped_column(sa.String(16))]

json_object = Annotated[dict[str, JSONValue], mapped_column(JSONB)]
"""A JSONB payload. Only for genuinely schemaless data -- raw event bodies, tool
arguments, calculation inputs. Everything with a known shape gets real columns."""


class TimestampMixin:
    """`created_at` and `updated_at`, both server-defaulted."""

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )


class CreatedAtMixin:
    """`created_at` only, for append-only tables that are never updated."""

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class SimulatedMixin:
    """Marks a row as originating from a simulated integration.

    `True` for every row in v1. The dashboard renders its SIMULATED badge from this
    column rather than from a hardcoded string, which makes rule 5 a property of the
    schema instead of a promise in a README.
    """

    is_simulated: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.true(), default=True
    )
