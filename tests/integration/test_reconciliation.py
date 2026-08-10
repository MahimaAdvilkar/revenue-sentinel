"""Reconciling an `INDETERMINATE` action (ADR-0025).

`INDETERMINATE` was reachable and inert for five sessions: the executor set it correctly
and nothing could resolve it. These tests cover the tooling that closes that, and most of
them are about what reconciliation **refuses** to do -- because every refusal here has an
attractive, dangerous alternative that a hurried implementation would have shipped.

The dangerous one worth naming: there is no retry. A retry becomes reachable only after a
person attests the effect did not occur. A "retry anyway" affordance on an uncertain
action looks helpful and duplicates real-world side effects.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import PROJECT_ROOT, Settings
from revenue_sentinel.core.ids import new_id
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import ActionStatus, ActionType
from revenue_sentinel.execution import reconciliation
from revenue_sentinel.execution.reconciliation import Outcome, ReconciliationError


@pytest.fixture
def uncertain(investigated: object, seeded_session: Session) -> gov_orm.ActionRecord:
    """One action left `INDETERMINATE`, reached the way the executor reaches it.

    Built on the golden run so the row has a real authorising policy evaluation -- the
    FK is `RESTRICT`, and an action with no authorisation is not representable.
    """
    executed = seeded_session.scalars(sa.select(gov_orm.ActionRecord)).first()
    assert executed is not None, "the golden run should have executed one Tier 1 action"

    record = gov_orm.ActionRecord(
        id=new_id(),
        run_id=executed.run_id,
        intervention_id=executed.intervention_id,
        action_type=ActionType.CRM_TASK,
        # A distinct key: this is a *different* effect, not a second attempt at the one
        # the golden run already completed.
        idempotency_key="idem-uncertain-0001",
        status=ActionStatus.INDETERMINATE,
        authorized_by=executed.authorized_by,
        attempt_count=1,
        target_ref="OPP-2001",
    )
    seeded_session.add(record)
    seeded_session.flush()
    return record


def _reconcile(
    session: Session,
    record: gov_orm.ActionRecord,
    settings: Settings,
    *,
    outcome: Outcome = Outcome.OCCURRED,
    actor: str = "usr:revenue-lead",
    evidence: str = "Checked HubSpot; task 1042 exists, created 12:00:03Z.",
) -> gov_orm.ActionRecord:
    return reconciliation.reconcile(
        session,
        action_record_id=record.id,
        outcome=outcome,
        actor=actor,
        evidence=evidence,
        occurred_at=settings.evaluation_timestamp,
    )


# ---------------------------------------------------------------------------
# Listing and the dossier
# ---------------------------------------------------------------------------
def test_only_indeterminate_actions_are_listed(
    uncertain: gov_orm.ActionRecord, seeded_session: Session
) -> None:
    """The golden run's own succeeded actions must not appear as work for a person."""
    rows = reconciliation.list_uncertain(seeded_session)

    assert [row.action_record_id for row in rows] == [uncertain.id]
    statuses = seeded_session.scalars(sa.select(gov_orm.ActionRecord.status)).all()
    assert ActionStatus.SUCCEEDED in statuses, "the fixture would be vacuous otherwise"


def test_the_listing_carries_what_an_operator_needs(
    uncertain: gov_orm.ActionRecord, seeded_session: Session
) -> None:
    row = reconciliation.list_uncertain(seeded_session)[0]

    assert row.incident_ref == "INC-001"
    assert row.action_type == ActionType.CRM_TASK.value
    assert row.target_ref == "OPP-2001"
    assert row.idempotency_key == uncertain.idempotency_key
    assert row.attempt_count == 1
    assert row.integration_status == "SIMULATED"
    assert str(uncertain.id) in row.reconcile_command
    assert "--evidence" in row.reconcile_command


def test_the_dossier_returns_the_authorising_context(
    uncertain: gov_orm.ActionRecord, seeded_session: Session
) -> None:
    """An operator deciding whether an effect happened needs to see what authorised it."""
    record = reconciliation.get_action(seeded_session, uncertain.id)

    assert record.authorized_by is not None
    assert record.idempotency_key == uncertain.idempotency_key
    assert record.status is ActionStatus.INDETERMINATE
    assert record.reconciled_by is None


def test_a_missing_action_is_refused(seeded_session: Session) -> None:
    with pytest.raises(ReconciliationError, match="no action record"):
        reconciliation.get_action(seeded_session, uuid4())


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------
def test_empty_evidence_is_refused(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    with pytest.raises(ReconciliationError, match="evidence is required"):
        _reconcile(seeded_session, uncertain, settings, evidence="")


def test_whitespace_only_evidence_is_refused(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    """The check is on content, not on the field being present."""
    with pytest.raises(ReconciliationError, match="evidence is required"):
        _reconcile(seeded_session, uncertain, settings, evidence="   \n\t  ")


def test_an_empty_actor_is_refused(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    with pytest.raises(ReconciliationError, match="--as is required"):
        _reconcile(seeded_session, uncertain, settings, actor="  ")


def test_a_non_indeterminate_action_is_refused(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    """There is nothing for a person to decide about a resolved action."""
    uncertain.status = ActionStatus.SUCCEEDED
    seeded_session.flush()

    with pytest.raises(ReconciliationError, match="not indeterminate"):
        _reconcile(seeded_session, uncertain, settings)


def test_reconciling_twice_is_refused(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    """An attestation is a record, not a draft."""
    _reconcile(seeded_session, uncertain, settings)

    with pytest.raises(ReconciliationError, match="already reconciled"):
        _reconcile(seeded_session, uncertain, settings, outcome=Outcome.DID_NOT_OCCUR)


def test_the_outcome_vocabulary_is_closed() -> None:
    """Two outcomes, and no "resolved but still unknown" -- that would be a way to
    close the question without answering it (ADR-0025)."""
    assert {outcome.value for outcome in Outcome} == {"occurred", "did-not-occur"}

    with pytest.raises(ValueError, match="not a valid"):
        Outcome("unknown")


def test_a_refused_reconciliation_leaves_the_action_untouched(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    """Refusals must not half-apply: no status change, no metadata, no audit event."""
    before = seeded_session.scalar(sa.select(sa.func.count()).select_from(obs_orm.AuditEvent))

    with pytest.raises(ReconciliationError):
        _reconcile(seeded_session, uncertain, settings, evidence="")

    seeded_session.refresh(uncertain)
    assert uncertain.status is ActionStatus.INDETERMINATE
    assert uncertain.reconciled_by is None
    assert uncertain.reconciled_at is None
    assert uncertain.reconciliation_evidence is None
    assert (
        seeded_session.scalar(sa.select(sa.func.count()).select_from(obs_orm.AuditEvent)) == before
    )


# ---------------------------------------------------------------------------
# The two resolutions
# ---------------------------------------------------------------------------
def test_occurred_resolves_to_succeeded(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    record = _reconcile(seeded_session, uncertain, settings, outcome=Outcome.OCCURRED)

    assert record.status is ActionStatus.SUCCEEDED


def test_did_not_occur_resolves_to_failed(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    record = _reconcile(seeded_session, uncertain, settings, outcome=Outcome.DID_NOT_OCCUR)

    assert record.status is ActionStatus.FAILED
    # Never back to PENDING: a retry is a separate, deliberate act after this attestation.
    assert record.status is not ActionStatus.PENDING


def test_the_attestation_is_persisted_on_the_row(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    record = _reconcile(seeded_session, uncertain, settings)

    assert record.reconciled_by == "usr:revenue-lead"
    assert record.reconciled_at == settings.evaluation_timestamp
    assert record.reconciliation_evidence is not None
    assert "task 1042" in record.reconciliation_evidence


def test_evidence_and_actor_are_stored_stripped(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    record = _reconcile(
        seeded_session, uncertain, settings, actor="  usr:lead  ", evidence="  saw it  "
    )

    assert record.reconciled_by == "usr:lead"
    assert record.reconciliation_evidence == "saw it"


# ---------------------------------------------------------------------------
# The guarantees that must survive reconciliation
# ---------------------------------------------------------------------------
def test_the_idempotency_key_is_never_released(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    """Reconciling to FAILED must not free the key for reuse.

    If it did, a later attempt would compute the same key, find nothing claimed, and
    perform an effect that may already exist -- which is the duplicate ADR-0017 exists
    to prevent.
    """
    key = uncertain.idempotency_key

    _reconcile(seeded_session, uncertain, settings, outcome=Outcome.DID_NOT_OCCUR)

    seeded_session.refresh(uncertain)
    assert uncertain.idempotency_key == key

    duplicate = gov_orm.ActionRecord(
        id=new_id(),
        run_id=uncertain.run_id,
        intervention_id=uncertain.intervention_id,
        action_type=uncertain.action_type,
        idempotency_key=key,
        status=ActionStatus.PENDING,
        authorized_by=uncertain.authorized_by,
        attempt_count=0,
        target_ref=uncertain.target_ref,
    )
    seeded_session.add(duplicate)
    with pytest.raises(sa.exc.IntegrityError):
        seeded_session.flush()
    seeded_session.rollback()


def test_reconciliation_performs_no_effect_and_no_retry(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    """Nothing is executed here. No tool call, no new action record, no attempt."""
    tool_calls_before = seeded_session.scalar(
        sa.select(sa.func.count()).select_from(obs_orm.ToolCall)
    )
    actions_before = seeded_session.scalar(
        sa.select(sa.func.count()).select_from(gov_orm.ActionRecord)
    )
    attempts_before = uncertain.attempt_count

    _reconcile(seeded_session, uncertain, settings, outcome=Outcome.DID_NOT_OCCUR)

    assert (
        seeded_session.scalar(sa.select(sa.func.count()).select_from(obs_orm.ToolCall))
        == tool_calls_before
    )
    assert (
        seeded_session.scalar(sa.select(sa.func.count()).select_from(gov_orm.ActionRecord))
        == actions_before
    )
    assert uncertain.attempt_count == attempts_before


def test_an_append_only_audit_event_records_the_attestation(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    _reconcile(seeded_session, uncertain, settings, outcome=Outcome.DID_NOT_OCCUR)

    event = seeded_session.scalars(
        sa.select(obs_orm.AuditEvent).where(
            obs_orm.AuditEvent.event_type == reconciliation.RECONCILED_EVENT
        )
    ).one()

    assert event.actor == "usr:revenue-lead"
    assert event.occurred_at == settings.evaluation_timestamp
    assert event.payload["previous_status"] == ActionStatus.INDETERMINATE.value
    assert event.payload["new_status"] == ActionStatus.FAILED.value
    assert event.payload["outcome"] == Outcome.DID_NOT_OCCUR.value
    assert "task 1042" in str(event.payload["evidence"])
    assert event.payload["idempotency_key"] == uncertain.idempotency_key
    # The record must never imply exactly-once delivery.
    assert "at-least-once" in str(event.payload["delivery"])
    assert "claimed, not authenticated" in str(event.payload["identity"])


def test_the_audit_event_survives_a_later_status_change(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    """Append-only: the event is history, not a mirror of the current row."""
    _reconcile(seeded_session, uncertain, settings, outcome=Outcome.DID_NOT_OCCUR)

    uncertain.status = ActionStatus.SUCCEEDED  # something else edits the row later
    seeded_session.flush()

    event = seeded_session.scalars(
        sa.select(obs_orm.AuditEvent).where(
            obs_orm.AuditEvent.event_type == reconciliation.RECONCILED_EVENT
        )
    ).one()
    assert event.payload["new_status"] == ActionStatus.FAILED.value


def test_the_schema_refuses_a_partial_attestation(
    uncertain: gov_orm.ActionRecord, seeded_session: Session
) -> None:
    """An actor with no evidence is an attestation with no basis (migration 0009 CHECK).

    Enforced in the database so the rule survives code that writes the row directly.
    """
    uncertain.reconciled_by = "usr:someone"
    uncertain.reconciled_at = datetime.fromisoformat("2026-08-01T12:00:00+00:00")
    uncertain.reconciliation_evidence = None

    with pytest.raises(sa.exc.IntegrityError, match="reconciliation_is_complete_or_absent"):
        seeded_session.flush()
    seeded_session.rollback()


def test_reconciled_rows_leave_the_uncertain_queue(
    uncertain: gov_orm.ActionRecord, seeded_session: Session, settings: Settings
) -> None:
    assert reconciliation.list_uncertain(seeded_session)

    _reconcile(seeded_session, uncertain, settings)

    assert reconciliation.list_uncertain(seeded_session) == []


def test_uuid_parsing_failures_are_the_callers_problem(seeded_session: Session) -> None:
    """The service takes a UUID; the CLI is where a bad string is turned into an error."""
    with pytest.raises(ValueError, match="badly formed"):
        UUID("not-a-uuid")


# ---------------------------------------------------------------------------
# Migration 0009
# ---------------------------------------------------------------------------
def _alembic(command: list[str], url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell, no user input
        [sys.executable, "-m", "alembic", *command],
        cwd=PROJECT_ROOT,
        env={**os.environ, "ALEMBIC_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )


def test_0009_round_trips_with_unreconciled_rows_present(
    dashboard: object, migrated_database_url: str, engine: Engine
) -> None:
    """Down and back up on data. Existing actions are simply unreconciled, which is true.

    The columns are additive and nullable precisely so this is safe -- an action recorded
    before the migration has no attestation, and saying so with NULL is honest.
    """
    # `dashboard` commits the whole golden run, so a real action record exists on disk --
    # the migration must be exercised against rows, not against an empty table.
    with Session(engine) as session:
        existing = session.scalars(sa.select(gov_orm.ActionRecord)).first()
        assert existing is not None, "the committed golden run should have executed an action"
        assert existing.reconciled_by is None

    down = _alembic(["downgrade", "0008"], migrated_database_url)
    assert down.returncode == 0, down.stderr

    columns = {column["name"] for column in sa.inspect(engine).get_columns("action_records")}
    assert "reconciled_by" not in columns

    up = _alembic(["upgrade", "head"], migrated_database_url)
    assert up.returncode == 0, up.stderr

    columns = {column["name"] for column in sa.inspect(engine).get_columns("action_records")}
    assert {"reconciled_by", "reconciled_at", "reconciliation_evidence"} <= columns


def test_0009_downgrade_refuses_to_discard_an_attestation(
    dashboard: object, migrated_database_url: str, engine: Engine
) -> None:
    """A human's finding about whether a real effect occurred is not dropped silently.

    Same posture as migration 0007 toward sub-cent spend: refuse, and say what to do.
    """
    with Session(engine) as session:
        record = session.scalars(sa.select(gov_orm.ActionRecord)).first()
        assert record is not None
        record.reconciled_by = "usr:auditor"
        record.reconciled_at = datetime.fromisoformat("2026-08-01T12:00:00+00:00")
        record.reconciliation_evidence = "verified against the provider console"
        session.commit()

    down = _alembic(["downgrade", "0008"], migrated_database_url)
    assert down.returncode != 0
    assert "attestation" in down.stderr

    with Session(engine) as session:
        record = session.scalars(sa.select(gov_orm.ActionRecord)).first()
        assert record is not None
        record.reconciled_by = None
        record.reconciled_at = None
        record.reconciliation_evidence = None
        session.commit()
