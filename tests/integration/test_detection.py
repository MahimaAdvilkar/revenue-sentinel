"""Detection against the full seeded data set.

Acceptance criterion 4 is the sharp one: the detector fires on `OPP-2001` **and on
nothing else**. A detector that fires on the golden scenario is easy; a detector
that stays quiet on the other fourteen opportunities is the actual claim.

Each background opportunity was seeded with a recorded reason for staying quiet, and
this file checks that the reason is the one that actually applies.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.db.models import events as event_orm
from revenue_sentinel.db.models import gtm as gtm_orm
from revenue_sentinel.domain.enums import Severity, SignalType
from revenue_sentinel.events.dispatcher import build_detection_context, run_detectors
from revenue_sentinel.events.ingest import ingest_source_events
from revenue_sentinel.events.normalize import normalize_pending
from revenue_sentinel.events.sources import read_source_events

TOTAL_OPPORTUNITIES = 15


def _prepare(session: Session, evaluated_at: datetime) -> None:
    ingest_source_events(session, read_source_events(session), received_at=evaluated_at)
    normalize_pending(session)


def test_exactly_one_signal_fires_across_the_whole_seed_set(
    seeded_session: Session, settings: Settings, evaluation_timestamp: datetime
) -> None:
    """Acceptance criterion 4."""
    _prepare(seeded_session, evaluation_timestamp)
    result, signals = run_detectors(
        seeded_session, evaluated_at=evaluation_timestamp, settings=settings
    )

    assert result.contexts_evaluated == TOTAL_OPPORTUNITIES
    assert result.signals_created == 1
    assert len(signals) == 1


def test_the_signal_is_on_the_golden_opportunity(
    seeded_session: Session, settings: Settings, evaluation_timestamp: datetime
) -> None:
    _prepare(seeded_session, evaluation_timestamp)
    _, signals = run_detectors(seeded_session, evaluated_at=evaluation_timestamp, settings=settings)

    signal = signals[0]
    opportunity = seeded_session.get(gtm_orm.Opportunity, signal.opportunity_id)
    account = seeded_session.get(gtm_orm.Account, signal.account_id)

    assert opportunity is not None
    assert account is not None
    assert opportunity.opportunity_ref == "OPP-2001"
    assert account.account_ref == "ACC-1001"
    assert signal.signal_type is SignalType.STALLED_OPPORTUNITY
    assert signal.severity is Severity.HIGH
    assert signal.detector_version == "stalled_opportunity/v1"


def test_no_background_opportunity_produces_a_signal(
    seeded_session: Session, settings: Settings, evaluation_timestamp: datetime
) -> None:
    """Fourteen opportunities stay quiet, each for its own recorded reason."""
    _prepare(seeded_session, evaluation_timestamp)
    _, signals = run_detectors(seeded_session, evaluated_at=evaluation_timestamp, settings=settings)

    fired_on = set()
    for signal in signals:
        opportunity = seeded_session.get(gtm_orm.Opportunity, signal.opportunity_id)
        if opportunity is not None:
            fired_on.add(opportunity.opportunity_ref)

    assert fired_on == {"OPP-2001"}


def test_the_internal_note_does_not_reset_the_inactivity_clock(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    """The seed carries a 3-day-old internal note on OPP-2001.

    If it counted as contact, `latest_sales_touch` would be 3 days old and the
    golden scenario would silently stop firing. This is the single most likely way
    for the demo to break without anyone noticing.
    """
    _prepare(seeded_session, evaluation_timestamp)
    opportunity = seeded_session.scalar(
        sa.select(gtm_orm.Opportunity).where(gtm_orm.Opportunity.opportunity_ref == "OPP-2001")
    )
    assert opportunity is not None

    context = build_detection_context(
        seeded_session, opportunity, evaluated_at=evaluation_timestamp
    )
    assert context is not None
    assert context.latest_sales_touch is not None
    assert (evaluation_timestamp - context.latest_sales_touch).days == 14


def test_the_detection_context_carries_the_full_usage_window(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    _prepare(seeded_session, evaluation_timestamp)
    opportunity = seeded_session.scalar(
        sa.select(gtm_orm.Opportunity).where(gtm_orm.Opportunity.opportunity_ref == "OPP-2001")
    )
    assert opportunity is not None

    context = build_detection_context(
        seeded_session, opportunity, evaluated_at=evaluation_timestamp
    )
    assert context is not None
    assert [snapshot.feature_events for snapshot in context.usage_window] == [1250, 1750]
    assert context.events


def test_the_signal_cites_the_events_it_was_derived_from(
    seeded_session: Session, settings: Settings, evaluation_timestamp: datetime
) -> None:
    """ "Why did this fire?" is answerable from stored data, not by re-running."""
    _prepare(seeded_session, evaluation_timestamp)
    _, signals = run_detectors(seeded_session, evaluated_at=evaluation_timestamp, settings=settings)

    refs = signals[0].evidence_refs
    assert refs

    known = set(seeded_session.scalars(sa.select(event_orm.NormalizedEvent.id)).all())
    assert {str(event_id) for event_id in known} >= set(refs)


def test_re_running_detection_creates_no_second_signal(
    seeded_session: Session, settings: Settings, evaluation_timestamp: datetime
) -> None:
    """Acceptance criterion 5, enforced by `UNIQUE (dedupe_key)`."""
    _prepare(seeded_session, evaluation_timestamp)
    run_detectors(seeded_session, evaluated_at=evaluation_timestamp, settings=settings)
    second, signals = run_detectors(
        seeded_session, evaluated_at=evaluation_timestamp, settings=settings
    )

    assert second.candidates == 1
    assert second.signals_created == 0
    assert second.deduplicated == 1
    assert signals == []

    stored = seeded_session.scalar(sa.select(sa.func.count()).select_from(event_orm.Signal))
    assert stored == 1


def test_signal_identity_is_reproducible(
    seeded_session: Session, settings: Settings, evaluation_timestamp: datetime
) -> None:
    """The surrogate id is derived from the dedupe key, so detection is
    reproducible end to end rather than only at the business-key level."""
    _prepare(seeded_session, evaluation_timestamp)
    _, first = run_detectors(seeded_session, evaluated_at=evaluation_timestamp, settings=settings)
    original_id = first[0].id

    seeded_session.execute(sa.delete(event_orm.Signal))
    seeded_session.flush()

    _, second = run_detectors(seeded_session, evaluated_at=evaluation_timestamp, settings=settings)
    assert second[0].id == original_id


def test_retuned_thresholds_change_what_fires(
    seeded_session: Session, settings: Settings, evaluation_timestamp: datetime
) -> None:
    """Raising the floor above the golden opportunity silences it.

    Proof the thresholds are load-bearing rather than decorative -- the detector
    reads its parameters instead of hard-coding the demo.
    """
    _prepare(seeded_session, evaluation_timestamp)
    strict = settings.model_copy(update={"detector_min_amount_usd": 1_000_000})

    result, signals = run_detectors(
        seeded_session, evaluated_at=evaluation_timestamp, settings=strict
    )
    assert result.signals_created == 0
    assert signals == []


def test_a_later_evaluation_day_is_a_new_window(
    seeded_session: Session, settings: Settings, evaluation_timestamp: datetime
) -> None:
    """`window_start` is part of the dedupe key, so a genuinely new window is a new
    signal -- deduplication suppresses repeats, not future detections."""
    from datetime import timedelta

    _prepare(seeded_session, evaluation_timestamp)
    run_detectors(seeded_session, evaluated_at=evaluation_timestamp, settings=settings)

    later = evaluation_timestamp + timedelta(days=1)
    result, signals = run_detectors(seeded_session, evaluated_at=later, settings=settings)

    assert result.signals_created == 1
    assert len(signals) == 1
