"""Raw and normalized events.

`RawEvent` is what arrived; `EventEnvelope` is the canonical shape every source is
normalized into, per `docs/event-model.md` §3. Detectors read envelopes, never raw
payloads, which is what keeps a detector independent of the source system that
produced its input.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.base import (
    AccountRef,
    DomainModel,
    NonEmptyStr,
    OpportunityRef,
    UtcDatetime,
)
from revenue_sentinel.domain.enums import EventType, SourceSystem, TrustLevel

ENVELOPE_SCHEMA_VERSION: Final = "1.0"
"""Bumped only on a breaking change to the envelope shape."""


class RawEvent(DomainModel):
    """An unmodified source payload. Append-only.

    `(source_system, source_event_id)` is UNIQUE in the database, which is what makes
    ingestion replay-safe: re-running produces no duplicates.
    """

    id: UUID
    source_system: SourceSystem
    source_event_id: NonEmptyStr
    received_at: UtcDatetime
    payload: JSONObject
    ingest_batch_id: UUID


class EventEnvelope(DomainModel):
    """The canonical normalized event.

    `trust_level` is not a variable. It is fixed at `UNTRUSTED` because there is no
    code path that marks ingested GTM content as trusted (rule 14), and the enum
    that types it has exactly one member so the guarantee survives into the database.
    """

    id: UUID
    raw_event_id: UUID
    schema_version: NonEmptyStr = ENVELOPE_SCHEMA_VERSION
    event_type: EventType
    source_system: SourceSystem
    occurred_at: UtcDatetime
    received_at: UtcDatetime
    account_ref: AccountRef | None = None
    opportunity_ref: OpportunityRef | None = None
    attributes: JSONObject
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
