"""Ingestion and normalization.

Acceptance criteria 1 and 2: re-running produces zero duplicate `raw_events`, and
every normalized event conforms to the canonical envelope with
`trust_level="untrusted"`.

The source feed is SIMULATED -- it replays the seeded GTM mirror. These tests
verify the pipeline, not a connection to anything external.
"""

from __future__ import annotations

from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.errors import DomainValidationError
from revenue_sentinel.db.models import events as orm
from revenue_sentinel.domain.enums import EMITTED_EVENT_TYPES, EventType, TrustLevel
from revenue_sentinel.domain.events import ENVELOPE_SCHEMA_VERSION
from revenue_sentinel.events.ingest import ingest_source_events
from revenue_sentinel.events.normalize import build_envelope, normalize_pending
from revenue_sentinel.events.sources import INGESTION_STATUS, read_source_events

EXPECTED_SOURCE_EVENTS = 72


def test_the_source_feed_is_labelled_simulated() -> None:
    """Rule 5. There is no code path in v1 that sets this to anything else."""
    assert INGESTION_STATUS == "SIMULATED"


def test_the_mirror_replays_one_event_per_business_record(seeded_session: Session) -> None:
    """15 opportunities + 17 activities + 20 usage + 15 engagement + 5 support."""
    events = read_source_events(seeded_session)
    assert len(events) == EXPECTED_SOURCE_EVENTS


def test_source_event_ids_are_stable_across_reads(seeded_session: Session) -> None:
    """Derived from business identity, not from a counter or a timestamp -- which
    is what makes database-level deduplication work on replay."""
    first = [event.source_event_id for event in read_source_events(seeded_session)]
    second = [event.source_event_id for event in read_source_events(seeded_session)]

    assert first == second
    assert len(set(first)) == len(first)


def test_source_events_come_back_in_a_stable_order(seeded_session: Session) -> None:
    ordered = [
        (event.source_system.value, event.source_event_id)
        for event in read_source_events(seeded_session)
    ]
    assert ordered == sorted(ordered)


# ---------------------------------------------------------------------------
# Replay safety at the raw-event level
# ---------------------------------------------------------------------------
def test_first_ingestion_inserts_everything(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    events = read_source_events(seeded_session)
    result = ingest_source_events(seeded_session, events, received_at=evaluation_timestamp)

    assert result.offered == EXPECTED_SOURCE_EVENTS
    assert result.inserted == EXPECTED_SOURCE_EVENTS
    assert result.duplicates == 0


def test_re_ingestion_inserts_nothing(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    """Acceptance criterion 1, enforced by `UNIQUE (source_system, source_event_id)`."""
    events = read_source_events(seeded_session)
    ingest_source_events(seeded_session, events, received_at=evaluation_timestamp)
    second = ingest_source_events(seeded_session, events, received_at=evaluation_timestamp)

    assert second.inserted == 0
    assert second.duplicates == EXPECTED_SOURCE_EVENTS

    stored = seeded_session.scalar(sa.select(sa.func.count()).select_from(orm.RawEvent))
    assert stored == EXPECTED_SOURCE_EVENTS


def test_ingesting_nothing_is_harmless(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    result = ingest_source_events(seeded_session, (), received_at=evaluation_timestamp)
    assert result.offered == 0
    assert result.inserted == 0


def test_each_pass_gets_its_own_batch_id(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    events = read_source_events(seeded_session)
    first = ingest_source_events(seeded_session, events, received_at=evaluation_timestamp)
    second = ingest_source_events(seeded_session, events, received_at=evaluation_timestamp)

    assert first.batch_id != second.batch_id


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
@pytest.fixture
def ingested(seeded_session: Session, evaluation_timestamp: datetime) -> Session:
    events = read_source_events(seeded_session)
    ingest_source_events(seeded_session, events, received_at=evaluation_timestamp)
    return seeded_session


def test_every_raw_event_normalizes(ingested: Session) -> None:
    result = normalize_pending(ingested)

    assert result.normalized == EXPECTED_SOURCE_EVENTS
    stored = ingested.scalar(sa.select(sa.func.count()).select_from(orm.NormalizedEvent))
    assert stored == EXPECTED_SOURCE_EVENTS


def test_normalization_is_idempotent(ingested: Session) -> None:
    """Selecting by absence rather than by batch makes a second pass a no-op --
    and lets a crash between ingest and normalize recover on the next cycle."""
    normalize_pending(ingested)
    second = normalize_pending(ingested)

    assert second.normalized == 0
    assert second.skipped_already_normalized == EXPECTED_SOURCE_EVENTS


def test_every_normalized_event_is_untrusted(ingested: Session) -> None:
    """Rule 14. `trust_level` is a constant on the envelope, not a parameter."""
    normalize_pending(ingested)

    levels = set(ingested.scalars(sa.select(orm.NormalizedEvent.trust_level)).all())
    assert levels == {TrustLevel.UNTRUSTED}


def test_no_normalized_event_carries_an_unemitted_type(ingested: Session) -> None:
    normalize_pending(ingested)

    types = set(ingested.scalars(sa.select(orm.NormalizedEvent.event_type)).all())
    assert types <= EMITTED_EVENT_TYPES


def test_every_envelope_carries_the_schema_version(ingested: Session) -> None:
    normalize_pending(ingested)

    versions = set(ingested.scalars(sa.select(orm.NormalizedEvent.schema_version)).all())
    assert versions == {ENVELOPE_SCHEMA_VERSION}


def test_business_references_survive_normalization(ingested: Session) -> None:
    normalize_pending(ingested)

    opportunity_events = ingested.scalars(
        sa.select(orm.NormalizedEvent).where(orm.NormalizedEvent.opportunity_ref == "OPP-2001")
    ).all()
    assert opportunity_events
    assert all(event.account_ref == "ACC-1001" for event in opportunity_events)


def test_untrusted_free_text_is_carried_verbatim(ingested: Session) -> None:
    """Adversarial content is preserved exactly, in a delimited data field -- never
    sanitised into something that looks safe and never concatenated into a prompt."""
    normalize_pending(ingested)

    event = ingested.scalar(
        sa.select(orm.NormalizedEvent).where(
            orm.NormalizedEvent.event_type == EventType.SUPPORT_ISSUE_OPENED,
            orm.NormalizedEvent.account_ref == "ACC-1001",
        )
    )
    assert event is not None
    assert "rate limit" in str(event.attributes["summary"]).lower()
    assert event.attributes["external_ref"] == "SUP-4411"


def test_an_unknown_event_type_is_rejected_not_passed_through(ingested: Session) -> None:
    """A payload we cannot type is a payload we cannot reason about."""
    raw = ingested.scalar(sa.select(orm.RawEvent).limit(1))
    assert raw is not None
    raw.payload = {**dict(raw.payload), "event_type": "crm.something.invented"}

    with pytest.raises(DomainValidationError, match="unknown event_type"):
        build_envelope(raw)


def test_a_declared_but_unemitted_type_is_rejected(ingested: Session) -> None:
    """The four contract-only types must not appear in v1 data."""
    raw = ingested.scalar(sa.select(orm.RawEvent).limit(1))
    assert raw is not None
    raw.payload = {
        **dict(raw.payload),
        "event_type": EventType.CRM_OPPORTUNITY_STAGE_CHANGED.value,
    }

    with pytest.raises(DomainValidationError, match="declared contract"):
        build_envelope(raw)


def test_a_payload_missing_occurred_at_is_rejected(ingested: Session) -> None:
    raw = ingested.scalar(sa.select(orm.RawEvent).limit(1))
    assert raw is not None
    payload = dict(raw.payload)
    payload.pop("occurred_at")
    raw.payload = payload

    with pytest.raises(DomainValidationError, match="occurred_at"):
        build_envelope(raw)


def test_each_normalized_event_links_back_to_its_raw_event(ingested: Session) -> None:
    normalize_pending(ingested)

    orphans = ingested.scalar(
        sa.select(sa.func.count())
        .select_from(orm.NormalizedEvent)
        .where(orm.NormalizedEvent.raw_event_id.not_in(sa.select(orm.RawEvent.id)))
    )
    assert orphans == 0
