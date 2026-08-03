"""Acceptance criterion 6: same seed, byte-identical rows.

The demo asserts on ordered output, so seeding must be reproducible rather than
merely correct. These tests compare a digest of every mirrored row across runs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.db.seeding import SEED_DIR, seed_database

MIRROR_TABLES = (
    orm.Account,
    orm.Opportunity,
    orm.Activity,
    orm.UsageSnapshot,
    orm.EngagementEvent,
    orm.SupportIssue,
    orm.CompanyProfile,
)

EXPECTED_COUNTS = {
    "accounts": 10,
    "opportunities": 15,
    "activities": 17,
    "usage_snapshots": 20,
    "engagement_events": 15,
    "support_issues": 5,
    "company_profiles": 10,
}


def _digest(session: Session) -> str:
    """A stable digest of every mirrored row.

    `created_at` is excluded deliberately: it is a server-side clock value, not seed
    output, and including it would make this test assert that time does not pass.
    """
    hasher = hashlib.sha256()
    for model in MIRROR_TABLES:
        table = model.__table__
        columns = [column for column in table.columns if column.name != "created_at"]
        ordered = sa.select(*columns).order_by(*[c for c in columns if c.name == "id"])
        for row in session.execute(ordered).mappings():
            payload = {key: _stringify(value) for key, value in row.items()}
            hasher.update(table.name.encode())
            hasher.update(json.dumps(payload, sort_keys=True).encode())
    return hasher.hexdigest()


def _stringify(value: object) -> object:
    if isinstance(value, Decimal | datetime):
        return str(value)
    if isinstance(value, dict | list | str | int | float | bool) or value is None:
        return value
    return str(value)


def test_seeding_twice_produces_an_identical_database(
    db_session: Session, settings: Settings
) -> None:
    seed_database(db_session, seed=settings.seed, evaluated_at=settings.evaluation_timestamp)
    first = _digest(db_session)

    seed_database(db_session, seed=settings.seed, evaluated_at=settings.evaluation_timestamp)
    second = _digest(db_session)

    assert first == second


def test_reseeding_is_idempotent_rather_than_duplicative(
    db_session: Session, settings: Settings
) -> None:
    """`make seed` twice must leave one copy of the fixture set, not two."""
    for _ in range(3):
        seed_database(db_session, seed=settings.seed, evaluated_at=settings.evaluation_timestamp)

    for model in MIRROR_TABLES:
        count = db_session.scalar(sa.select(sa.func.count()).select_from(model))
        assert count == EXPECTED_COUNTS[model.__tablename__], model.__tablename__


def test_row_counts_match_the_fixture_files(db_session: Session, settings: Settings) -> None:
    """The database must hold exactly what the fixtures declare -- no more, no fewer."""
    summary = seed_database(
        db_session, seed=settings.seed, evaluated_at=settings.evaluation_timestamp
    )

    for filename, key in (
        ("accounts.json", "accounts"),
        ("opportunities.json", "opportunities"),
        ("activities.json", "activities"),
        ("usage.json", "usage_snapshots"),
        ("engagement.json", "engagement_events"),
        ("support.json", "support_issues"),
        ("enrichment.json", "company_profiles"),
    ):
        declared = json.loads((SEED_DIR / filename).read_text(encoding="utf-8"))[key]
        stored = db_session.scalar(
            sa.select(sa.func.count()).select_from(
                {
                    "accounts": orm.Account,
                    "opportunities": orm.Opportunity,
                    "activities": orm.Activity,
                    "usage_snapshots": orm.UsageSnapshot,
                    "engagement_events": orm.EngagementEvent,
                    "support_issues": orm.SupportIssue,
                    "company_profiles": orm.CompanyProfile,
                }[key]
            )
        )
        assert stored == len(declared), filename

    assert summary.total == sum(EXPECTED_COUNTS.values())


def test_a_different_seed_changes_identity_but_not_the_scenario(
    db_session: Session, settings: Settings
) -> None:
    """SEED controls surrogate keys; the business data is fixture-declared.

    This is what lets the scenario stay pinned to the documented figures while row
    identity remains seed-derived and therefore reproducible.
    """
    seed_database(db_session, seed=settings.seed, evaluated_at=settings.evaluation_timestamp)
    original_id = db_session.scalar(
        sa.select(orm.Opportunity.id).where(orm.Opportunity.opportunity_ref == "OPP-2001")
    )
    original_amount = db_session.scalar(
        sa.select(orm.Opportunity.amount).where(orm.Opportunity.opportunity_ref == "OPP-2001")
    )

    seed_database(db_session, seed=999, evaluated_at=settings.evaluation_timestamp)
    reseeded_id = db_session.scalar(
        sa.select(orm.Opportunity.id).where(orm.Opportunity.opportunity_ref == "OPP-2001")
    )
    reseeded_amount = db_session.scalar(
        sa.select(orm.Opportunity.amount).where(orm.Opportunity.opportunity_ref == "OPP-2001")
    )

    assert reseeded_id != original_id
    assert reseeded_amount == original_amount == Decimal("180000.00")


def test_a_different_evaluation_instant_shifts_the_scenario_intact(
    db_session: Session, settings: Settings
) -> None:
    """The 14-day gap is relative, so the scenario does not decay overnight."""
    shifted = settings.evaluation_timestamp.replace(year=2027)
    seed_database(db_session, seed=settings.seed, evaluated_at=shifted)

    latest_touch = db_session.scalar(
        sa.select(sa.func.max(orm.Activity.occurred_at)).where(
            orm.Activity.opportunity_id
            == sa.select(orm.Opportunity.id)
            .where(orm.Opportunity.opportunity_ref == "OPP-2001")
            .scalar_subquery(),
            orm.Activity.activity_type.in_(["email", "call", "meeting"]),
        )
    )
    assert latest_touch is not None
    assert (shifted - latest_touch).days == 14


def test_no_float_reaches_a_money_column(db_session: Session, settings: Settings) -> None:
    """`NUMERIC` must round-trip exactly -- 180000.00, not 179999.99999999997."""
    seed_database(db_session, seed=settings.seed, evaluated_at=settings.evaluation_timestamp)

    amounts = db_session.scalars(sa.select(orm.Opportunity.amount)).all()
    assert amounts
    for amount in amounts:
        assert isinstance(amount, Decimal)

    exact = db_session.scalar(
        sa.select(orm.Opportunity.amount).where(orm.Opportunity.opportunity_ref == "OPP-2001")
    )
    assert exact == Decimal("180000.00")
    assert str(exact) == "180000.00"
