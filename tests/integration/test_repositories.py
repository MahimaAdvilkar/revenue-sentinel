"""Repository behaviour.

The contract these tests pin down is that repositories return **domain models**, not
ORM rows. Everything above `db/` depends on that: a leaked ORM object would carry
lazy loading and session identity into layers that have no session.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from revenue_sentinel.core.errors import NotFoundError
from revenue_sentinel.db.repositories import (
    AccountRepository,
    ActivityRepository,
    CompanyProfileRepository,
    EngagementEventRepository,
    OpportunityRepository,
    SupportIssueRepository,
    UsageSnapshotRepository,
)
from revenue_sentinel.domain.gtm import Account, Activity, Opportunity


def test_account_is_returned_as_a_domain_model(seeded_session: Session) -> None:
    account = AccountRepository(seeded_session).get_by_ref("ACC-1001")

    assert isinstance(account, Account)
    assert account.account_ref == "ACC-1001"


def test_domain_models_returned_by_repositories_are_frozen(seeded_session: Session) -> None:
    account = AccountRepository(seeded_session).require_by_ref("ACC-1001")
    with pytest.raises(ValidationError, match="frozen"):
        account.name = "Mutated"  # type: ignore[misc]


def test_missing_account_returns_none(seeded_session: Session) -> None:
    assert AccountRepository(seeded_session).get_by_ref("ACC-0000") is None


def test_require_by_ref_raises_a_typed_not_found(seeded_session: Session) -> None:
    with pytest.raises(NotFoundError) as caught:
        AccountRepository(seeded_session).require_by_ref("ACC-0000")

    assert caught.value.entity == "account"
    assert caught.value.ref == "ACC-0000"


def test_accounts_list_in_reference_order(seeded_session: Session) -> None:
    refs = [account.account_ref for account in AccountRepository(seeded_session).list_all()]

    assert refs == sorted(refs)
    assert refs[0] == "ACC-1001"
    assert len(refs) == 10


def test_account_lookup_by_id_matches_lookup_by_ref(seeded_session: Session) -> None:
    repository = AccountRepository(seeded_session)
    by_ref = repository.require_by_ref("ACC-1001")
    by_id = repository.get_by_id(by_ref.id)

    assert by_id == by_ref


def test_opportunity_is_returned_with_exact_money(seeded_session: Session) -> None:
    opportunity = OpportunityRepository(seeded_session).require_by_ref("OPP-2001")

    assert isinstance(opportunity, Opportunity)
    assert opportunity.amount == Decimal("180000.00")


def test_opportunities_scope_to_their_account(seeded_session: Session) -> None:
    account = AccountRepository(seeded_session).require_by_ref("ACC-1002")
    opportunities = OpportunityRepository(seeded_session).list_for_account(account.id)

    assert {o.opportunity_ref for o in opportunities} == {"OPP-2002", "OPP-2011"}
    for opportunity in opportunities:
        assert opportunity.account_id == account.id


def test_missing_opportunity_raises_not_found(seeded_session: Session) -> None:
    with pytest.raises(NotFoundError, match="opportunity"):
        OpportunityRepository(seeded_session).require_by_ref("OPP-0000")


def test_activities_come_back_newest_first(seeded_session: Session) -> None:
    account = AccountRepository(seeded_session).require_by_ref("ACC-1001")
    activities = ActivityRepository(seeded_session).list_for_account(account.id)

    assert len(activities) == 5
    occurred = [activity.occurred_at for activity in activities]
    assert occurred == sorted(occurred, reverse=True)


def test_latest_activity_for_an_opportunity_is_the_most_recent(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    opportunity = OpportunityRepository(seeded_session).require_by_ref("OPP-2001")
    latest = ActivityRepository(seeded_session).latest_for_opportunity(opportunity.id)

    assert isinstance(latest, Activity)
    assert (evaluation_timestamp - latest.occurred_at).days == 3


def test_latest_activity_is_none_for_an_opportunity_with_no_activity(
    seeded_session: Session,
) -> None:
    assert ActivityRepository(seeded_session).latest_for_opportunity(uuid4()) is None


def test_usage_snapshots_come_back_oldest_first(seeded_session: Session) -> None:
    account = AccountRepository(seeded_session).require_by_ref("ACC-1001")
    snapshots = UsageSnapshotRepository(seeded_session).list_for_account(account.id)

    assert [s.period_start for s in snapshots] == sorted(s.period_start for s in snapshots)


def test_usage_window_query_excludes_periods_outside_the_range(
    seeded_session: Session, evaluation_timestamp: datetime
) -> None:
    account = AccountRepository(seeded_session).require_by_ref("ACC-1001")
    repository = UsageSnapshotRepository(seeded_session)
    end = evaluation_timestamp.date()

    recent = repository.list_in_window(account.id, start=end - timedelta(days=7), end=end)
    everything = repository.list_in_window(account.id, start=end - timedelta(days=30), end=end)

    assert len(recent) == 1
    assert len(everything) == 2
    assert recent[0].feature_events == 1750


def test_engagement_and_support_scope_to_their_account(seeded_session: Session) -> None:
    account = AccountRepository(seeded_session).require_by_ref("ACC-1001")

    engagement = EngagementEventRepository(seeded_session).list_for_account(account.id)
    support = SupportIssueRepository(seeded_session).list_for_account(account.id)

    assert len(engagement) == 4
    assert len(support) == 1
    assert all(event.account_id == account.id for event in engagement)


def test_company_profile_is_one_per_account(seeded_session: Session) -> None:
    account = AccountRepository(seeded_session).require_by_ref("ACC-1001")
    profile = CompanyProfileRepository(seeded_session).get_for_account(account.id)

    assert profile is not None
    assert profile.hq_country == "United States"
    assert profile.tech_stack["cloud"] == "aws"
    assert profile.is_simulated is True


def test_company_profile_is_none_for_an_unknown_account(seeded_session: Session) -> None:
    assert CompanyProfileRepository(seeded_session).get_for_account(uuid4()) is None


def test_counts_match_the_seeded_fixture_set(seeded_session: Session) -> None:
    assert AccountRepository(seeded_session).count() == 10
    assert OpportunityRepository(seeded_session).count() == 15
    assert ActivityRepository(seeded_session).count() == 17
    assert UsageSnapshotRepository(seeded_session).count() == 20
    assert EngagementEventRepository(seeded_session).count() == 15
    assert SupportIssueRepository(seeded_session).count() == 5
    assert CompanyProfileRepository(seeded_session).count() == 10


def test_timestamps_on_returned_models_are_timezone_aware(seeded_session: Session) -> None:
    account = AccountRepository(seeded_session).require_by_ref("ACC-1001")

    assert account.created_at.tzinfo is not None
    assert account.updated_at.tzinfo is not None
