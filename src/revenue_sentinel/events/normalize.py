"""Normalization: raw payloads to the canonical envelope.

Detectors read envelopes, never raw payloads. That is what keeps a detector
independent of the source system that produced its input -- and what will let
Session 4 swap a simulated adapter for a real one without touching `signals/`.

Two rules hold for every normalizer:

* **`trust_level` is always `untrusted`.** It is a constant on the envelope model,
  not a parameter, so no normalizer can raise it (rule 14).
* **Unknown event types are rejected, not passed through.** A payload we cannot
  type is a payload we cannot reason about, and letting it through would put
  unvalidated source data in front of a detector.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.errors import DomainValidationError
from revenue_sentinel.core.ids import new_id
from revenue_sentinel.core.types import JSONObject, JSONValue
from revenue_sentinel.db.models import events as orm
from revenue_sentinel.domain.enums import EMITTED_EVENT_TYPES, EventType, SourceSystem, TrustLevel
from revenue_sentinel.domain.events import ENVELOPE_SCHEMA_VERSION, EventEnvelope


@dataclass(frozen=True, slots=True)
class NormalizeResult:
    """What one normalization pass did."""

    normalized: int
    skipped_already_normalized: int


def _as_object(value: JSONValue, label: str) -> JSONObject:
    if not isinstance(value, dict):
        raise DomainValidationError(f"{label} must be a JSON object, got {type(value).__name__}")
    return value


def _optional_ref(data: JSONObject, key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainValidationError(f"{key} must be a string when present")
    return value


def build_envelope(raw: orm.RawEvent) -> EventEnvelope:
    """Turn one raw event into a validated canonical envelope.

    Raises `DomainValidationError` on an unknown or non-emitted event type, and
    pydantic raises on anything that fails envelope validation -- a malformed
    payload stops here rather than reaching a detector.
    """
    payload = _as_object(raw.payload, "raw_events.payload")

    raw_type = payload.get("event_type")
    if not isinstance(raw_type, str):
        raise DomainValidationError(f"raw event {raw.id} has no event_type")
    try:
        event_type = EventType(raw_type)
    except ValueError as exc:
        raise DomainValidationError(f"unknown event_type {raw_type!r}") from exc
    if event_type not in EMITTED_EVENT_TYPES:
        raise DomainValidationError(
            f"{event_type.value} is a declared contract, not an emitted type in v1"
        )

    occurred_raw = payload.get("occurred_at")
    if not isinstance(occurred_raw, str):
        raise DomainValidationError(f"raw event {raw.id} has no occurred_at")
    occurred_at = datetime.fromisoformat(occurred_raw)

    data = _as_object(payload.get("data"), "raw_events.payload.data")

    return EventEnvelope(
        id=new_id(),
        raw_event_id=raw.id,
        schema_version=ENVELOPE_SCHEMA_VERSION,
        event_type=event_type,
        source_system=SourceSystem(raw.source_system),
        occurred_at=occurred_at,
        received_at=raw.received_at,
        account_ref=_optional_ref(data, "account_ref"),
        opportunity_ref=_optional_ref(data, "opportunity_ref"),
        attributes=data,
        # Not a parameter. There is no code path that marks ingested content
        # trusted, and the enum has one member so there is nothing else to pass.
        trust_level=TrustLevel.UNTRUSTED,
    )


def normalize_pending(session: Session) -> NormalizeResult:
    """Normalize every raw event that does not yet have a normalized row.

    Selecting by absence rather than by batch makes this idempotent and lets it
    recover: a crash between ingest and normalize leaves work that the next cycle
    picks up, with no bookkeeping to get wrong.
    """
    already = sa.select(orm.NormalizedEvent.raw_event_id)
    pending = session.scalars(
        sa.select(orm.RawEvent)
        .where(orm.RawEvent.id.not_in(already))
        .order_by(orm.RawEvent.source_system, orm.RawEvent.source_event_id)
    ).all()

    total_raw = session.scalar(sa.select(sa.func.count()).select_from(orm.RawEvent)) or 0

    for raw in pending:
        envelope = build_envelope(raw)
        session.add(
            orm.NormalizedEvent(
                id=envelope.id,
                raw_event_id=envelope.raw_event_id,
                schema_version=envelope.schema_version,
                event_type=envelope.event_type,
                source_system=envelope.source_system,
                occurred_at=envelope.occurred_at,
                received_at=envelope.received_at,
                account_ref=envelope.account_ref,
                opportunity_ref=envelope.opportunity_ref,
                attributes=envelope.attributes,
                trust_level=envelope.trust_level,
            )
        )
    session.flush()

    return NormalizeResult(
        normalized=len(pending),
        skipped_already_normalized=total_raw - len(pending),
    )
