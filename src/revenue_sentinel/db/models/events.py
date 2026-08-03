"""Event, normalization, and signal tables.

Two of the four idempotency boundaries in `docs/event-model.md` §6 live here:
`UNIQUE (source_system, source_event_id)` makes ingestion replay-safe, and
`UNIQUE (dedupe_key)` stops a second incident opening for the same condition.
Both are database constraints, not application checks.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from revenue_sentinel.core.types import JSONValue
from revenue_sentinel.db.base import (
    Base,
    CreatedAtMixin,
    digest,
    json_object,
    pg_enum,
    short_text,
    timestamp_tz,
    uuid_fk,
    uuid_pk,
)
from revenue_sentinel.domain.enums import (
    EventType,
    Severity,
    SignalType,
    SourceSystem,
    TrustLevel,
)


class RawEvent(Base, CreatedAtMixin):
    """Append-only. Never updated, never deleted."""

    __tablename__ = "raw_events"

    id: Mapped[uuid_pk]
    source_system: Mapped[SourceSystem] = mapped_column(pg_enum(SourceSystem, "source_system"))
    source_event_id: Mapped[short_text]
    received_at: Mapped[timestamp_tz]
    payload: Mapped[json_object]
    ingest_batch_id: Mapped[uuid_fk]

    __table_args__ = (
        sa.UniqueConstraint(
            "source_system", "source_event_id", name="uq_raw_events_source_system_source_event_id"
        ),
        sa.Index("ix_raw_events_ingest_batch_id", "ingest_batch_id"),
    )


class NormalizedEvent(Base, CreatedAtMixin):
    """The canonical envelope. `trust_level` is always `untrusted` (rule 14)."""

    __tablename__ = "normalized_events"

    id: Mapped[uuid_pk]
    raw_event_id: Mapped[uuid_fk] = mapped_column(
        sa.ForeignKey("raw_events.id", ondelete="CASCADE"), unique=True
    )
    schema_version: Mapped[str] = mapped_column(sa.String(16))
    event_type: Mapped[EventType] = mapped_column(pg_enum(EventType, "event_type"))
    source_system: Mapped[SourceSystem] = mapped_column(pg_enum(SourceSystem, "source_system"))
    occurred_at: Mapped[timestamp_tz]
    received_at: Mapped[timestamp_tz]
    account_ref: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    opportunity_ref: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    attributes: Mapped[json_object]
    trust_level: Mapped[TrustLevel] = mapped_column(
        pg_enum(TrustLevel, "trust_level"), server_default=TrustLevel.UNTRUSTED.value
    )

    __table_args__ = (
        sa.Index("ix_normalized_events_event_type_occurred_at", "event_type", "occurred_at"),
        sa.Index("ix_normalized_events_opportunity_ref", "opportunity_ref"),
        sa.Index("ix_normalized_events_account_ref", "account_ref"),
    )


class Signal(Base, CreatedAtMixin):
    __tablename__ = "signals"

    id: Mapped[uuid_pk]
    signal_type: Mapped[SignalType] = mapped_column(pg_enum(SignalType, "signal_type"))
    detector_version: Mapped[str] = mapped_column(sa.String(32))
    severity: Mapped[Severity] = mapped_column(pg_enum(Severity, "severity"))
    account_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("accounts.id", ondelete="CASCADE"))
    opportunity_id: Mapped[uuid_fk | None] = mapped_column(
        sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=True
    )
    detected_at: Mapped[timestamp_tz]
    dedupe_key: Mapped[digest] = mapped_column(unique=True)
    evidence_refs: Mapped[list[JSONValue]] = mapped_column(JSONB, default=list)

    __table_args__ = (sa.Index("ix_signals_signal_type_detected_at", "signal_type", "detected_at"),)
