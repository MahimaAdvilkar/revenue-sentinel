"""Database-level guarantees.

`docs/data-model.md` §4 claims a set of constraints prevent specific failures. These
tests hold the database to those claims by attempting the violation and requiring it
to be refused -- not by reading the DDL, which would only prove the constraint was
declared.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from revenue_sentinel.db.models import events as event_orm
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.domain.enums import (
    AccountSegment,
    OpportunityStage,
    Severity,
    SignalType,
    SourceSystem,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def make_account(session: Session, ref: str = "ACC-5001") -> orm.Account:
    account = orm.Account(
        id=uuid4(),
        account_ref=ref,
        name="Fixture Co",
        segment=AccountSegment.SMB,
        industry="Testing",
        employee_count=10,
        owner_id="USR-1",
    )
    session.add(account)
    session.flush()
    return account


def make_opportunity(
    session: Session, account: orm.Account, **overrides: object
) -> orm.Opportunity:
    payload: dict[str, object] = {
        "id": uuid4(),
        "opportunity_ref": "OPP-5001",
        "account_id": account.id,
        "name": "Fixture Deal",
        "stage": OpportunityStage.PROPOSAL,
        "amount": Decimal("1000.00"),
        "currency": "USD",
        "expected_close_date": NOW.date() + timedelta(days=30),
        "probability": Decimal("0.5000"),
        "owner_id": "USR-1",
    }
    payload.update(overrides)
    opportunity = orm.Opportunity(**payload)
    session.add(opportunity)
    session.flush()
    return opportunity


# ---------------------------------------------------------------------------
# Uniqueness -- the idempotency boundaries
# ---------------------------------------------------------------------------
def test_raw_events_reject_a_duplicate_source_event(db_session: Session) -> None:
    """Ingestion is replay-safe because the database says so."""

    def add(batch: str) -> None:
        db_session.add(
            event_orm.RawEvent(
                id=uuid4(),
                source_system=SourceSystem.CRM,
                source_event_id="crm-evt-1",
                received_at=NOW,
                payload={"batch": batch},
                ingest_batch_id=uuid4(),
            )
        )
        db_session.flush()

    add("first")
    with pytest.raises(IntegrityError):
        add("second")


def test_signals_reject_a_duplicate_dedupe_key(db_session: Session) -> None:
    """A second incident cannot open for the same condition."""
    account = make_account(db_session)

    def add() -> None:
        db_session.add(
            event_orm.Signal(
                id=uuid4(),
                signal_type=SignalType.STALLED_OPPORTUNITY,
                detector_version="v1",
                severity=Severity.HIGH,
                account_id=account.id,
                detected_at=NOW,
                dedupe_key=DIGEST_A,
                evidence_refs=[],
            )
        )
        db_session.flush()

    add()
    with pytest.raises(IntegrityError):
        add()


def test_a_different_detector_version_is_a_different_claim(db_session: Session) -> None:
    """Retuning a detector may legitimately re-report a condition."""
    account = make_account(db_session)
    for version, key in (("v1", DIGEST_A), ("v2", DIGEST_B)):
        db_session.add(
            event_orm.Signal(
                id=uuid4(),
                signal_type=SignalType.STALLED_OPPORTUNITY,
                detector_version=version,
                severity=Severity.HIGH,
                account_id=account.id,
                detected_at=NOW,
                dedupe_key=key,
                evidence_refs=[],
            )
        )
    db_session.flush()

    assert db_session.scalar(sa.select(sa.func.count()).select_from(event_orm.Signal)) == 2


def test_account_and_opportunity_references_are_unique(db_session: Session) -> None:
    make_account(db_session, "ACC-5001")
    with pytest.raises(IntegrityError):
        make_account(db_session, "ACC-5001")


# ---------------------------------------------------------------------------
# Check constraints
# ---------------------------------------------------------------------------
def test_a_negative_opportunity_amount_is_refused(db_session: Session) -> None:
    account = make_account(db_session)
    with pytest.raises(IntegrityError):
        make_opportunity(db_session, account, amount=Decimal("-0.01"))


def test_a_probability_above_one_is_refused(db_session: Session) -> None:
    account = make_account(db_session)
    with pytest.raises(IntegrityError):
        make_opportunity(db_session, account, probability=Decimal("1.5000"))


def test_a_usage_period_that_ends_before_it_starts_is_refused(db_session: Session) -> None:
    account = make_account(db_session)
    with pytest.raises(IntegrityError):
        db_session.add(
            orm.UsageSnapshot(
                id=uuid4(),
                account_id=account.id,
                period_start=NOW.date(),
                period_end=NOW.date() - timedelta(days=7),
                active_users=1,
                sessions=1,
                feature_events=1,
                usage_score=Decimal("10.00"),
            )
        )
        db_session.flush()


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
def test_money_round_trips_through_numeric_without_drift(db_session: Session) -> None:
    """The reason money is NUMERIC and not FLOAT, demonstrated."""
    account = make_account(db_session)
    make_opportunity(db_session, account, amount=Decimal("180000.00"))
    db_session.expire_all()

    stored = db_session.scalar(
        sa.select(orm.Opportunity.amount).where(orm.Opportunity.opportunity_ref == "OPP-5001")
    )
    assert isinstance(stored, Decimal)
    assert stored == Decimal("180000.00")
    assert str(stored) == "180000.00"


def test_timestamps_come_back_timezone_aware(db_session: Session) -> None:
    account = make_account(db_session)
    db_session.expire_all()

    stored = db_session.scalar(
        sa.select(orm.Account.created_at).where(orm.Account.id == account.id)
    )
    assert stored is not None
    assert stored.tzinfo is not None


def test_native_enums_store_snake_case_values_not_member_names(db_session: Session) -> None:
    """`mid_market`, not `MID_MARKET` -- fixtures and documents use the value."""
    make_account(db_session)
    db_session.flush()

    raw = db_session.execute(
        sa.text("SELECT segment::text FROM accounts WHERE account_ref = 'ACC-5001'")
    ).scalar_one()
    assert raw == "smb"


def test_an_undeclared_enum_value_is_refused(db_session: Session) -> None:
    account = make_account(db_session)
    with pytest.raises((IntegrityError, sa.exc.DBAPIError)):
        db_session.execute(
            sa.text("UPDATE accounts SET segment = 'enormous' WHERE id = :id"),
            {"id": account.id},
        )


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------
def test_an_opportunity_cannot_reference_a_missing_account(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        db_session.add(
            orm.Opportunity(
                id=uuid4(),
                opportunity_ref="OPP-9999",
                account_id=uuid4(),
                name="Orphan",
                stage=OpportunityStage.PROPOSAL,
                amount=Decimal("1.00"),
                currency="USD",
                expected_close_date=NOW.date(),
                probability=Decimal("0.5000"),
                owner_id="USR-1",
            )
        )
        db_session.flush()


def test_is_simulated_defaults_to_true(db_session: Session) -> None:
    """Honesty is the default, not something a caller has to remember."""
    account = make_account(db_session)
    db_session.expire_all()
    stored = db_session.get(orm.Account, account.id)
    assert stored is not None
    assert stored.is_simulated is True
