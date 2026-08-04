"""The `stalled_opportunity` detector.

The detector decides whether a human gets paged about a $180,000 deal, so the tests
that matter are the boundaries: 13 days versus 14, 39% versus 40%, $99,999.99 versus
$100,000.00. A threshold that is right in the middle of its range and wrong at its
edge passes a naive test suite and fails in production.

Every test builds its own `DetectionContext`. No database, no clock, no
configuration -- which is the whole claim being verified.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from revenue_sentinel.domain.enums import (
    AccountSegment,
    EventType,
    OpportunityStage,
    Severity,
    SignalType,
    SourceSystem,
)
from revenue_sentinel.domain.events import EventEnvelope
from revenue_sentinel.domain.gtm import Account, Opportunity, UsageSnapshot
from revenue_sentinel.signals.detectors.stalled_opportunity import (
    DETECTOR_VERSION,
    StalledOpportunityDetector,
    StalledOpportunityParams,
)
from revenue_sentinel.signals.protocol import DetectionContext

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

PARAMS = StalledOpportunityParams(
    min_amount_usd=Decimal("100000"),
    inactivity_days=14,
    usage_growth=Decimal("0.40"),
)
DETECTOR = StalledOpportunityDetector(params=PARAMS)


def an_account() -> Account:
    return Account(
        id=uuid4(),
        account_ref="ACC-1001",
        name="Northwind Logistics",
        segment=AccountSegment.MID_MARKET,
        industry="Transportation & Logistics",
        employee_count=850,
        owner_id="USR-77",
        created_at=NOW,
        updated_at=NOW,
    )


def an_opportunity(**overrides: object) -> Opportunity:
    payload: dict[str, object] = {
        "id": uuid4(),
        "opportunity_ref": "OPP-2001",
        "account_id": uuid4(),
        "name": "Northwind Logistics - Platform Expansion",
        "stage": OpportunityStage.PROPOSAL,
        "amount": Decimal("180000.00"),
        "currency": "USD",
        "expected_close_date": date(2026, 9, 15),
        "probability": Decimal("0.6000"),
        "owner_id": "USR-77",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return Opportunity.model_validate(payload)


def usage(earlier: int, later: int) -> tuple[UsageSnapshot, ...]:
    def snapshot(start_days_ago: int, feature_events: int) -> UsageSnapshot:
        start = (NOW - timedelta(days=start_days_ago)).date()
        return UsageSnapshot(
            id=uuid4(),
            account_id=uuid4(),
            period_start=start,
            period_end=start + timedelta(days=6),
            active_users=12,
            sessions=96,
            feature_events=feature_events,
            usage_score=Decimal("61.50"),
            created_at=NOW,
        )

    return (snapshot(14, earlier), snapshot(7, later))


def a_context(**overrides: object) -> DetectionContext:
    defaults: dict[str, object] = {
        "evaluated_at": NOW,
        "account": an_account(),
        "opportunity": an_opportunity(),
        "latest_sales_touch": NOW - timedelta(days=14),
        "usage_window": usage(1250, 1750),
        "events": (),
    }
    defaults.update(overrides)
    return DetectionContext(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The golden scenario
# ---------------------------------------------------------------------------
def test_fires_on_the_golden_scenario() -> None:
    candidate = DETECTOR.evaluate(a_context())

    assert candidate is not None
    assert candidate.signal_type is SignalType.STALLED_OPPORTUNITY
    assert candidate.detector_version == DETECTOR_VERSION
    assert candidate.severity is Severity.HIGH
    assert candidate.detected_at == NOW


def test_the_detector_is_pure() -> None:
    """Same input twice, identical output. This is why `evaluate` returns a
    candidate without a surrogate id -- a fresh UUID would break it."""
    context = a_context()
    assert DETECTOR.evaluate(context) == DETECTOR.evaluate(context)


def test_two_equivalent_contexts_produce_the_same_dedupe_key() -> None:
    assert DETECTOR.dedupe_key(a_context()) == DETECTOR.dedupe_key(a_context())


# ---------------------------------------------------------------------------
# Each condition is necessary -- remove one and it stops firing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("stage", [OpportunityStage.CLOSED_WON, OpportunityStage.CLOSED_LOST])
def test_closed_stages_never_fire(stage: OpportunityStage) -> None:
    assert DETECTOR.evaluate(a_context(opportunity=an_opportunity(stage=stage))) is None


@pytest.mark.parametrize(
    "stage",
    [OpportunityStage.DISCOVERY, OpportunityStage.PROPOSAL, OpportunityStage.NEGOTIATION],
)
def test_every_open_stage_can_fire(stage: OpportunityStage) -> None:
    assert DETECTOR.evaluate(a_context(opportunity=an_opportunity(stage=stage))) is not None


@pytest.mark.parametrize(
    ("amount", "fires"),
    [
        (Decimal("99999.99"), False),
        (Decimal("100000.00"), True),
        (Decimal("100000.01"), True),
        (Decimal("0.00"), False),
    ],
)
def test_amount_floor_boundary(amount: Decimal, fires: bool) -> None:
    candidate = DETECTOR.evaluate(a_context(opportunity=an_opportunity(amount=amount)))
    assert (candidate is not None) is fires


@pytest.mark.parametrize(
    ("days", "fires"),
    [(0, False), (13, False), (14, True), (15, True), (200, True)],
)
def test_inactivity_boundary(days: int, fires: bool) -> None:
    candidate = DETECTOR.evaluate(a_context(latest_sales_touch=NOW - timedelta(days=days)))
    assert (candidate is not None) is fires


@pytest.mark.parametrize(
    ("earlier", "later", "fires"),
    [
        (1250, 1737, False),  # +38.96%
        (1250, 1750, True),  # +40.00% exactly -- the documented value
        (1250, 1751, True),
        (1250, 1250, False),  # flat
        (1250, 900, False),  # declining
    ],
)
def test_usage_growth_boundary(earlier: int, later: int, fires: bool) -> None:
    candidate = DETECTOR.evaluate(a_context(usage_window=usage(earlier, later)))
    assert (candidate is not None) is fires


def test_all_four_conditions_are_required() -> None:
    """Break each one in turn; none of them is optional."""
    breakers: list[dict[str, object]] = [
        {"opportunity": an_opportunity(stage=OpportunityStage.CLOSED_WON)},
        {"opportunity": an_opportunity(amount=Decimal("50000.00"))},
        {"latest_sales_touch": NOW - timedelta(days=2)},
        {"usage_window": usage(1250, 1250)},
    ]
    for breaker in breakers:
        assert DETECTOR.evaluate(a_context(**breaker)) is None
    assert DETECTOR.evaluate(a_context()) is not None


# ---------------------------------------------------------------------------
# Missing or unusable data does not fire
# ---------------------------------------------------------------------------
def test_no_recorded_sales_touch_does_not_fire() -> None:
    """Absent history is not evidence of a stall."""
    assert DETECTOR.evaluate(a_context(latest_sales_touch=None)) is None


def test_a_single_usage_snapshot_does_not_fire() -> None:
    """One week is not a trend."""
    assert DETECTOR.evaluate(a_context(usage_window=usage(1250, 1750)[:1])) is None


def test_no_usage_data_does_not_fire() -> None:
    assert DETECTOR.evaluate(a_context(usage_window=())) is None


def test_a_zero_usage_baseline_does_not_fire() -> None:
    """Growth from zero is undefined; a first week of usage is not a stall."""
    assert DETECTOR.evaluate(a_context(usage_window=usage(0, 1750))) is None


def test_a_non_usd_opportunity_does_not_fire() -> None:
    """v1 holds no exchange rates. Converting at an unstated rate would fabricate
    the number this system promises not to fabricate."""
    assert DETECTOR.evaluate(a_context(opportunity=an_opportunity(currency="EUR"))) is None


# ---------------------------------------------------------------------------
# Dedupe key
# ---------------------------------------------------------------------------
def test_dedupe_key_is_a_sha256_digest() -> None:
    key = DETECTOR.dedupe_key(a_context())
    assert len(key) == 64
    assert set(key) <= set("0123456789abcdef")


def test_dedupe_key_is_stable_across_the_same_day() -> None:
    """`window_start` is truncated to the date, so two runs hours apart agree.

    Without truncation, replay safety would hold under the frozen demo clock and
    silently fail under a real one.
    """
    morning = DETECTOR.dedupe_key(a_context(evaluated_at=NOW.replace(hour=1)))
    evening = DETECTOR.dedupe_key(a_context(evaluated_at=NOW.replace(hour=23)))
    assert morning == evening


def test_dedupe_key_changes_with_the_opportunity() -> None:
    other = an_opportunity(opportunity_ref="OPP-2002")
    assert DETECTOR.dedupe_key(a_context()) != DETECTOR.dedupe_key(a_context(opportunity=other))


def test_dedupe_key_changes_with_the_detector_version() -> None:
    """Retuning a detector is a new claim, not a duplicate of the old one."""
    retuned = StalledOpportunityDetector(
        params=StalledOpportunityParams(
            min_amount_usd=Decimal("100000"),
            inactivity_days=21,
            usage_growth=Decimal("0.40"),
        )
    )
    # A different window shifts window_start, which is part of the key.
    assert DETECTOR.dedupe_key(a_context()) != retuned.dedupe_key(a_context())


def test_dedupe_key_changes_on_a_different_day() -> None:
    later = a_context(evaluated_at=NOW + timedelta(days=1))
    assert DETECTOR.dedupe_key(a_context()) != DETECTOR.dedupe_key(later)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------
def test_evidence_refs_cite_the_events_that_support_the_condition() -> None:
    events = (
        _event(EventType.CRM_ACTIVITY_LOGGED),
        _event(EventType.PRODUCT_USAGE_ROLLUP),
        _event(EventType.SUPPORT_ISSUE_OPENED),
    )
    candidate = DETECTOR.evaluate(a_context(events=events))

    assert candidate is not None
    assert len(candidate.evidence_refs) == 2
    assert str(events[2].id) not in candidate.evidence_refs


def test_evidence_refs_are_sorted_so_output_is_stable() -> None:
    events = tuple(_event(EventType.CRM_ACTIVITY_LOGGED) for _ in range(5))
    candidate = DETECTOR.evaluate(a_context(events=events))

    assert candidate is not None
    assert list(candidate.evidence_refs) == sorted(candidate.evidence_refs)


def _event(event_type: EventType) -> EventEnvelope:
    return EventEnvelope(
        id=uuid4(),
        raw_event_id=uuid4(),
        event_type=event_type,
        source_system=SourceSystem.CRM,
        occurred_at=NOW,
        received_at=NOW,
        attributes={},
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
def test_detector_reports_itself_as_implemented() -> None:
    assert DETECTOR.is_implemented is True


def test_the_window_follows_the_inactivity_threshold() -> None:
    assert DETECTOR.window == timedelta(days=14)


def test_detector_is_frozen_so_thresholds_cannot_drift_mid_run() -> None:
    with pytest.raises((AttributeError, TypeError)):
        DETECTOR.params = PARAMS  # type: ignore[misc]
