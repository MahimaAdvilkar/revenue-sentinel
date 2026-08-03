"""Acceptance criterion 7: the golden scenario is present and exactly as documented.

Every assertion here mirrors a specific line in `docs/demo-scenario.md` §1. If the
documentation and the seed data ever disagree, this file fails and one of the two is
wrong -- which is the only way to keep a document authoritative over time.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.analytics.pipeline_impact import calculate_pipeline_impact
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.db.repositories import (
    AccountRepository,
    ActivityRepository,
    EngagementEventRepository,
    OpportunityRepository,
    SupportIssueRepository,
    UsageSnapshotRepository,
)
from revenue_sentinel.domain.enums import (
    AccountSegment,
    ActivityType,
    EngagementEventType,
    OpportunityStage,
    SupportSeverity,
    SupportStatus,
)

ACCOUNT_REF = "ACC-1001"
OPPORTUNITY_REF = "OPP-2001"


def test_northwind_logistics_is_seeded_as_documented(seeded_session: Session) -> None:
    account = AccountRepository(seeded_session).require_by_ref(ACCOUNT_REF)

    assert account.name == "Northwind Logistics"
    assert account.segment is AccountSegment.MID_MARKET
    assert account.industry == "Transportation & Logistics"
    assert account.employee_count == 850
    assert account.owner_id == "USR-77"


def test_the_opportunity_is_180k_at_proposal(seeded_session: Session) -> None:
    opportunity = OpportunityRepository(seeded_session).require_by_ref(OPPORTUNITY_REF)

    assert opportunity.amount == Decimal("180000.00")
    assert opportunity.currency == "USD"
    assert opportunity.stage is OpportunityStage.PROPOSAL
    assert opportunity.probability == Decimal("0.6000")
    assert opportunity.owner_id == "USR-77"


def test_the_close_date_is_45_days_out(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    opportunity = OpportunityRepository(seeded_session).require_by_ref(OPPORTUNITY_REF)
    assert (opportunity.expected_close_date - evaluation_timestamp.date()).days == 45


def test_the_last_sales_touch_is_exactly_fourteen_days_old(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    """The inactivity half of the stalled-opportunity conjunction."""
    opportunity = OpportunityRepository(seeded_session).require_by_ref(OPPORTUNITY_REF)
    latest_touch = seeded_session.scalar(
        sa.select(sa.func.max(orm.Activity.occurred_at)).where(
            orm.Activity.opportunity_id == opportunity.id,
            orm.Activity.activity_type.in_(
                [ActivityType.EMAIL, ActivityType.CALL, ActivityType.MEETING]
            ),
        )
    )
    assert latest_touch is not None
    assert (evaluation_timestamp - latest_touch).days == 14


def test_an_internal_note_does_not_reset_the_inactivity_clock(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    """A rep talking to themselves is not contact with the buyer.

    The fixture deliberately contains a 3-day-old internal note. If the Session 2
    detector counted it, the golden scenario would silently stop firing.
    """
    opportunity = OpportunityRepository(seeded_session).require_by_ref(OPPORTUNITY_REF)
    latest_of_any_kind = ActivityRepository(seeded_session).latest_for_opportunity(opportunity.id)

    assert latest_of_any_kind is not None
    assert latest_of_any_kind.activity_type is ActivityType.NOTE
    assert (evaluation_timestamp - latest_of_any_kind.occurred_at).days == 3


def test_usage_grew_by_exactly_forty_percent(seeded_session: Session) -> None:
    """The engagement half of the conjunction: 1,250 -> 1,750 feature events."""
    account = AccountRepository(seeded_session).require_by_ref(ACCOUNT_REF)
    snapshots = UsageSnapshotRepository(seeded_session).list_for_account(account.id)

    assert len(snapshots) == 2
    earlier, later = snapshots
    assert earlier.feature_events == 1250
    assert later.feature_events == 1750
    assert earlier.active_users == 12
    assert later.active_users == 19

    growth = (Decimal(later.feature_events) - Decimal(earlier.feature_events)) / Decimal(
        earlier.feature_events
    )
    assert growth == Decimal("0.40")


def test_engagement_shows_opens_and_clicks_but_no_meetings(seeded_session: Session) -> None:
    """The sharpest detail in the scenario: the buyer engages, nobody meets them."""
    account = AccountRepository(seeded_session).require_by_ref(ACCOUNT_REF)
    events = EngagementEventRepository(seeded_session).list_for_account(account.id)

    by_type = [event.event_type for event in events]
    assert by_type.count(EngagementEventType.OPENED) == 2
    assert by_type.count(EngagementEventType.CLICKED) == 1
    assert EngagementEventType.MEETING_HELD not in by_type


def test_there_is_one_open_p3_support_issue(seeded_session: Session) -> None:
    account = AccountRepository(seeded_session).require_by_ref(ACCOUNT_REF)
    issues = SupportIssueRepository(seeded_session).list_for_account(account.id)

    assert len(issues) == 1
    assert issues[0].severity is SupportSeverity.P3
    assert issues[0].status is SupportStatus.OPEN
    assert "rate limit" in issues[0].summary.lower()


def test_the_seeded_scenario_produces_the_documented_impact_figures(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    """End to end: read the seeded rows, run the calculator, get the demo numbers.

    This is the assertion that ties the fixture data to the figure spoken aloud in
    the demo. Either could drift; together they cannot.
    """
    opportunity = OpportunityRepository(seeded_session).require_by_ref(OPPORTUNITY_REF)
    account = AccountRepository(seeded_session).require_by_ref(ACCOUNT_REF)
    earlier, later = UsageSnapshotRepository(seeded_session).list_for_account(account.id)

    latest_touch = seeded_session.scalar(
        sa.select(sa.func.max(orm.Activity.occurred_at)).where(
            orm.Activity.opportunity_id == opportunity.id,
            orm.Activity.activity_type.in_(
                [ActivityType.EMAIL, ActivityType.CALL, ActivityType.MEETING]
            ),
        )
    )
    assert latest_touch is not None

    growth = (Decimal(later.feature_events) - Decimal(earlier.feature_events)) / Decimal(
        earlier.feature_events
    )
    impact = calculate_pipeline_impact(
        amount=opportunity.amount,
        currency=opportunity.currency,
        probability=opportunity.probability,
        days_inactive=(evaluation_timestamp - latest_touch).days,
        stage=opportunity.stage,
        usage_growth=growth,
    )

    assert impact.weighted_value == Decimal("108000.00")
    assert impact.at_risk_value == Decimal("32130.00")


def test_every_mirrored_row_is_marked_simulated(seeded_session: Session) -> None:
    """Rule 5 as a property of the data, not a promise in a README."""
    for model in (
        orm.Account,
        orm.Opportunity,
        orm.Activity,
        orm.UsageSnapshot,
        orm.EngagementEvent,
        orm.SupportIssue,
        orm.CompanyProfile,
    ):
        unmarked = seeded_session.scalar(
            sa.select(sa.func.count()).select_from(model).where(model.is_simulated.is_(False))
        )
        assert unmarked == 0, f"{model.__tablename__} contains rows not marked simulated"
