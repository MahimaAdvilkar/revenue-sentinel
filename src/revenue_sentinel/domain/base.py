"""The base model and the constrained scalar types every domain model is built from.

Two rules are enforced here rather than repeated in thirty places:

* **Money is `Decimal`, never `float`.** Pipeline impact is the number the whole
  product is judged on and float drift in a demo is an unforced error.
* **Datetimes are timezone-aware.** A naive datetime is rejected, not assumed-UTC.
  An assumption here resurfaces as an off-by-hours bug in "days since last activity".

Models are frozen and reject unknown fields. `from_attributes` lets repositories
build them straight from ORM rows; it is a pydantic feature, so `domain/` stays free
of any persistence import (boundary R1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints


def _require_utc(value: datetime) -> datetime:
    """Reject naive datetimes; normalize aware ones to UTC."""
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


class DomainModel(BaseModel):
    """Base for every domain model: immutable, closed, ORM-friendly."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
        use_enum_values=False,
    )


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------
UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]

Money = Annotated[Decimal, Field(max_digits=14, decimal_places=2, ge=0)]
"""Currency amount. Matches `NUMERIC(14, 2)`; non-negative by construction."""

CostAmount = Annotated[Decimal, Field(max_digits=12, decimal_places=6, ge=0)]
"""Sub-cent model spend. Matches `NUMERIC(12, 6)`."""

Probability = Annotated[Decimal, Field(ge=0, le=1, max_digits=5, decimal_places=4)]
"""A probability or confidence in [0, 1]."""

Score = Annotated[Decimal, Field(ge=0, le=100, max_digits=6, decimal_places=2)]
"""A 0-100 score: usage health, effort, risk, composite ranking."""

CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
"""ISO-4217, e.g. `USD`."""

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A lowercase hex SHA-256 -- dedupe keys, idempotency keys, state digests."""

TraceId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
SpanId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]

# Business references. Validated as patterns so a malformed reference from a
# fixture or an external system fails at the boundary (rule 14).
AccountRef = Annotated[str, StringConstraints(pattern=r"^ACC-[0-9]{4}$")]
OpportunityRef = Annotated[str, StringConstraints(pattern=r"^OPP-[0-9]{4}$")]
IncidentRef = Annotated[str, StringConstraints(pattern=r"^INC-[0-9]{3}$")]
EvidenceRef = Annotated[str, StringConstraints(pattern=r"^EV-[0-9]{3}$")]
HypothesisRef = Annotated[str, StringConstraints(pattern=r"^HYP-[0-9]{3}$")]
UserRef = Annotated[str, StringConstraints(pattern=r"^USR-[0-9]{1,4}$")]
