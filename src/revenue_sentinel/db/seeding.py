"""Deterministic seeding of the GTM source mirror.

Determinism here is total, and it comes from removing sources of variation rather
than from controlling them:

* **No random number generator.** Every business value is declared in
  `fixtures/seed/*.json`. There is nothing left to randomise.
* **No wall clock.** Fixtures express time as *days before the evaluation instant*,
  and that instant is injected. "14 days ago" is 14 days from a fixed reference, so
  the scenario does not decay overnight.
* **Derived identity.** Surrogate UUIDs come from `deterministic_uuid(seed, ...)`,
  keyed on the business reference. Row identity is a pure function of the seed and
  the business key, and therefore independent of insertion order.

The consequence is the property acceptance criterion 6 asks for: the same seed
produces byte-identical rows, and re-running the seeder is idempotent rather than
duplicative.

Every row written here is marked `is_simulated = True` (rule 5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import FIXTURES_DIR
from revenue_sentinel.core.errors import ConfigurationError
from revenue_sentinel.core.ids import deterministic_uuid
from revenue_sentinel.core.types import JSONObject, JSONValue
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.domain.enums import (
    AccountSegment,
    ActivityDirection,
    ActivityType,
    EngagementChannel,
    EngagementEventType,
    OpportunityStage,
    SupportSeverity,
    SupportStatus,
)

SEED_DIR: Final[Path] = FIXTURES_DIR / "seed"

# Insert order matters only for foreign keys; delete order is its reverse.
_TABLES_IN_DEPENDENCY_ORDER: Final = (
    orm.Account,
    orm.Opportunity,
    orm.Activity,
    orm.UsageSnapshot,
    orm.EngagementEvent,
    orm.SupportIssue,
    orm.CompanyProfile,
)


@dataclass(frozen=True, slots=True)
class SeedSummary:
    """Row counts written, for the CLI to print and tests to assert on."""

    accounts: int
    opportunities: int
    activities: int
    usage_snapshots: int
    engagement_events: int
    support_issues: int
    company_profiles: int

    @property
    def total(self) -> int:
        return (
            self.accounts
            + self.opportunities
            + self.activities
            + self.usage_snapshots
            + self.engagement_events
            + self.support_issues
            + self.company_profiles
        )


def _load(filename: str, key: str) -> list[JSONObject]:
    """Read one fixture file and return its row list."""
    path = SEED_DIR / filename
    if not path.is_file():
        raise ConfigurationError(f"seed fixture missing: {path}")
    payload: JSONValue = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigurationError(f"seed fixture {filename} must contain a JSON object")
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise ConfigurationError(f"seed fixture {filename} has no '{key}' array")
    result: list[JSONObject] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ConfigurationError(f"seed fixture {filename} contains a non-object row")
        result.append(row)
    return result


def _text(row: JSONObject, field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str):
        raise ConfigurationError(f"fixture field {field!r} must be a string, got {value!r}")
    return value


def _whole(row: JSONObject, field: str) -> int:
    value = row.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(f"fixture field {field!r} must be an integer, got {value!r}")
    return value


def _decimal(row: JSONObject, field: str) -> Decimal:
    """Decimals arrive as strings so no float ever touches a money value."""
    return Decimal(_text(row, field))


def _instant(evaluated_at: datetime, days_before: int) -> datetime:
    return evaluated_at - timedelta(days=days_before)


def _day(evaluated_at: datetime, days_before: int) -> date:
    return (evaluated_at - timedelta(days=days_before)).date()


def clear_seed_data(session: Session) -> None:
    """Delete every mirrored GTM row.

    Scoped to the seven source-mirror tables only. It does not touch incidents,
    workflow runs, or the audit trail -- re-seeding source data must not silently
    erase the record of what the system did with the previous copy.
    """
    for model in reversed(_TABLES_IN_DEPENDENCY_ORDER):
        session.execute(sa.delete(model))


def seed_database(session: Session, *, seed: int, evaluated_at: datetime) -> SeedSummary:
    """Load the fixture set into the GTM mirror.

    Idempotent: existing mirror rows are cleared first, so running `make seed` twice
    produces the same database rather than two copies of it.
    """
    if evaluated_at.tzinfo is None:
        raise ConfigurationError("evaluated_at must be timezone-aware")
    evaluated_at = evaluated_at.astimezone(UTC)

    clear_seed_data(session)

    account_ids = _seed_accounts(session, seed=seed)
    opportunity_ids = _seed_opportunities(session, seed=seed, accounts=account_ids, at=evaluated_at)
    activities = _seed_activities(
        session, seed=seed, accounts=account_ids, opportunities=opportunity_ids, at=evaluated_at
    )
    usage = _seed_usage(session, seed=seed, accounts=account_ids, at=evaluated_at)
    engagement = _seed_engagement(session, seed=seed, accounts=account_ids, at=evaluated_at)
    support = _seed_support(session, seed=seed, accounts=account_ids, at=evaluated_at)
    profiles = _seed_profiles(session, seed=seed, accounts=account_ids, at=evaluated_at)

    session.flush()
    return SeedSummary(
        accounts=len(account_ids),
        opportunities=len(opportunity_ids),
        activities=activities,
        usage_snapshots=usage,
        engagement_events=engagement,
        support_issues=support,
        company_profiles=profiles,
    )


def _seed_accounts(session: Session, *, seed: int) -> dict[str, UUID]:
    ids: dict[str, UUID] = {}
    for row in _load("accounts.json", "accounts"):
        ref = _text(row, "account_ref")
        row_id = deterministic_uuid(seed, "account", ref)
        ids[ref] = row_id
        session.add(
            orm.Account(
                id=row_id,
                account_ref=ref,
                name=_text(row, "name"),
                segment=AccountSegment(_text(row, "segment")),
                industry=_text(row, "industry"),
                employee_count=_whole(row, "employee_count"),
                owner_id=_text(row, "owner_id"),
                is_simulated=True,
            )
        )
    session.flush()
    return ids


def _seed_opportunities(
    session: Session, *, seed: int, accounts: dict[str, UUID], at: datetime
) -> dict[str, UUID]:
    ids: dict[str, UUID] = {}
    for row in _load("opportunities.json", "opportunities"):
        ref = _text(row, "opportunity_ref")
        account_ref = _text(row, "account_ref")
        row_id = deterministic_uuid(seed, "opportunity", ref)
        ids[ref] = row_id
        session.add(
            orm.Opportunity(
                id=row_id,
                opportunity_ref=ref,
                account_id=accounts[account_ref],
                name=_text(row, "name"),
                stage=OpportunityStage(_text(row, "stage")),
                amount=_decimal(row, "amount"),
                currency=_text(row, "currency"),
                # `close_in_days` counts forward from the evaluation instant, so it
                # is negated into the "days before" convention the helpers use. A
                # negative value therefore lands in the past, which is correct for
                # the closed-won and closed-lost background opportunities.
                expected_close_date=_day(at, -_whole(row, "close_in_days")),
                probability=_decimal(row, "probability"),
                owner_id=_text(row, "owner_id"),
                is_simulated=True,
            )
        )
    session.flush()
    return ids


def _seed_activities(
    session: Session,
    *,
    seed: int,
    accounts: dict[str, UUID],
    opportunities: dict[str, UUID],
    at: datetime,
) -> int:
    rows = _load("activities.json", "activities")
    for index, row in enumerate(rows):
        account_ref = _text(row, "account_ref")
        opportunity_ref = row.get("opportunity_ref")
        session.add(
            orm.Activity(
                id=deterministic_uuid(seed, "activity", account_ref, str(index)),
                account_id=accounts[account_ref],
                opportunity_id=(
                    opportunities[opportunity_ref] if isinstance(opportunity_ref, str) else None
                ),
                activity_type=ActivityType(_text(row, "activity_type")),
                direction=ActivityDirection(_text(row, "direction")),
                occurred_at=_instant(at, _whole(row, "days_before_evaluation")),
                subject=_text(row, "subject"),
                body=_text(row, "body"),
                is_simulated=True,
            )
        )
    session.flush()
    return len(rows)


def _seed_usage(session: Session, *, seed: int, accounts: dict[str, UUID], at: datetime) -> int:
    rows = _load("usage.json", "usage_snapshots")
    for row in rows:
        account_ref = _text(row, "account_ref")
        start_offset = _whole(row, "period_start_days_before")
        session.add(
            orm.UsageSnapshot(
                id=deterministic_uuid(seed, "usage", account_ref, str(start_offset)),
                account_id=accounts[account_ref],
                period_start=_day(at, start_offset),
                period_end=_day(at, _whole(row, "period_end_days_before")),
                active_users=_whole(row, "active_users"),
                sessions=_whole(row, "sessions"),
                feature_events=_whole(row, "feature_events"),
                usage_score=_decimal(row, "usage_score"),
                is_simulated=True,
            )
        )
    session.flush()
    return len(rows)


def _seed_engagement(
    session: Session, *, seed: int, accounts: dict[str, UUID], at: datetime
) -> int:
    rows = _load("engagement.json", "engagement_events")
    for index, row in enumerate(rows):
        account_ref = _text(row, "account_ref")
        session.add(
            orm.EngagementEvent(
                id=deterministic_uuid(seed, "engagement", account_ref, str(index)),
                account_id=accounts[account_ref],
                channel=EngagementChannel(_text(row, "channel")),
                event_type=EngagementEventType(_text(row, "event_type")),
                occurred_at=_instant(at, _whole(row, "days_before_evaluation")),
                is_simulated=True,
            )
        )
    session.flush()
    return len(rows)


def _seed_support(session: Session, *, seed: int, accounts: dict[str, UUID], at: datetime) -> int:
    rows = _load("support.json", "support_issues")
    for row in rows:
        account_ref = _text(row, "account_ref")
        external_ref = _text(row, "external_ref")
        session.add(
            orm.SupportIssue(
                id=deterministic_uuid(seed, "support", external_ref),
                account_id=accounts[account_ref],
                external_ref=external_ref,
                severity=SupportSeverity(_text(row, "severity")),
                status=SupportStatus(_text(row, "status")),
                opened_at=_instant(at, _whole(row, "days_before_evaluation")),
                summary=_text(row, "summary"),
                is_simulated=True,
            )
        )
    session.flush()
    return len(rows)


def _seed_profiles(session: Session, *, seed: int, accounts: dict[str, UUID], at: datetime) -> int:
    rows = _load("enrichment.json", "company_profiles")
    for row in rows:
        account_ref = _text(row, "account_ref")
        tech_stack = row.get("tech_stack")
        if not isinstance(tech_stack, dict):
            raise ConfigurationError(f"tech_stack for {account_ref} must be a JSON object")
        session.add(
            orm.CompanyProfile(
                id=deterministic_uuid(seed, "profile", account_ref),
                account_id=accounts[account_ref],
                hq_country=_text(row, "hq_country"),
                revenue_band=_text(row, "revenue_band"),
                tech_stack=tech_stack,
                enriched_at=_instant(at, _whole(row, "enriched_days_before_evaluation")),
                source=_text(row, "source"),
                is_simulated=True,
            )
        )
    session.flush()
    return len(rows)
