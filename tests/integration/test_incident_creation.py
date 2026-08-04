"""Incident creation and lifecycle persistence.

Acceptance criteria 5, 6 and 8: deduplication prevents a second incident, lifecycle
transitions are persisted, illegal transitions are rejected, and the full cycle
produces `INC-001`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.db.models import events as event_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.domain.enums import IncidentStatus, IncidentType, Severity
from revenue_sentinel.events.pipeline import run_ingestion_cycle
from revenue_sentinel.incidents.lifecycle import IllegalTransitionError
from revenue_sentinel.incidents.service import (
    AUDIT_INCIDENT_OPENED,
    AUDIT_INCIDENT_TRANSITIONED,
    SIGNAL_AGENT_ACTOR,
    allocate_incident_ref,
    open_incident_for_signal,
    transition_incident,
)


@pytest.fixture
def cycled(seeded_session: Session, settings: Settings, evaluation_timestamp: datetime) -> Session:
    """One full ingestion cycle, leaving exactly one incident."""
    run_ingestion_cycle(seeded_session, evaluated_at=evaluation_timestamp, settings=settings)
    return seeded_session


def _the_incident(session: Session) -> workflow_orm.Incident:
    incident = session.scalar(sa.select(workflow_orm.Incident))
    assert incident is not None
    return incident


# ---------------------------------------------------------------------------
# The cycle produces INC-001
# ---------------------------------------------------------------------------
def test_one_cycle_opens_exactly_one_incident(cycled: Session) -> None:
    count = cycled.scalar(sa.select(sa.func.count()).select_from(workflow_orm.Incident))
    assert count == 1


def test_the_incident_is_inc_001(cycled: Session) -> None:
    assert _the_incident(cycled).incident_ref == "INC-001"


def test_the_incident_matches_the_documented_scenario(cycled: Session) -> None:
    incident = _the_incident(cycled)

    assert incident.incident_type is IncidentType.STALLED_OPPORTUNITY
    assert incident.severity is Severity.HIGH
    assert incident.status is IncidentStatus.TRIAGED
    assert incident.closed_at is None


def test_the_title_names_the_opportunity_without_repeating_the_account(
    cycled: Session,
) -> None:
    """CRM opportunity names already lead with the account name."""
    title = _the_incident(cycled).title

    assert title == "Northwind Logistics - Platform Expansion stalled at proposal"
    assert title.count("Northwind Logistics") == 1


def test_the_incident_points_at_the_signal_that_produced_it(cycled: Session) -> None:
    incident = _the_incident(cycled)
    signal = cycled.get(event_orm.Signal, incident.signal_id)

    assert signal is not None
    assert signal.severity == incident.severity


# ---------------------------------------------------------------------------
# Replay safety at the incident level
# ---------------------------------------------------------------------------
def test_a_second_cycle_opens_no_second_incident(
    cycled: Session, settings: Settings, evaluation_timestamp: datetime
) -> None:
    """Acceptance criterion 5, end to end."""
    summary = run_ingestion_cycle(cycled, evaluated_at=evaluation_timestamp, settings=settings)

    assert summary.raw_inserted == 0
    assert summary.signals_created == 0
    assert summary.signals_deduplicated == 1
    assert summary.incidents_opened == 0

    count = cycled.scalar(sa.select(sa.func.count()).select_from(workflow_orm.Incident))
    assert count == 1


def test_two_incidents_cannot_share_a_signal(cycled: Session) -> None:
    """The third replay-safety boundary: `UNIQUE (signal_id)`.

    It holds even if raw-event and signal deduplication were both bypassed.
    """
    incident = _the_incident(cycled)
    signal = cycled.get(event_orm.Signal, incident.signal_id)
    assert signal is not None

    with pytest.raises(IntegrityError):
        open_incident_for_signal(cycled, signal, occurred_at=incident.opened_at)


def test_incident_references_increment(cycled: Session) -> None:
    first = allocate_incident_ref(cycled)
    second = allocate_incident_ref(cycled)

    assert first != second
    assert first.startswith("INC-")
    assert int(first.removeprefix("INC-")) + 1 == int(second.removeprefix("INC-"))


# ---------------------------------------------------------------------------
# Lifecycle persistence
# ---------------------------------------------------------------------------
def test_opening_walks_detected_then_triaged(cycled: Session) -> None:
    """The documented lifecycle is followed rather than skipped to a convenient state."""
    transitions = cycled.scalars(
        sa.select(obs_orm.AuditEvent)
        .where(obs_orm.AuditEvent.event_type == AUDIT_INCIDENT_TRANSITIONED)
        .order_by(obs_orm.AuditEvent.occurred_at)
    ).all()

    assert len(transitions) == 1
    assert transitions[0].payload["from_status"] == "detected"
    assert transitions[0].payload["to_status"] == "triaged"


def test_opening_writes_an_audit_event(cycled: Session) -> None:
    opened = cycled.scalar(
        sa.select(obs_orm.AuditEvent).where(obs_orm.AuditEvent.event_type == AUDIT_INCIDENT_OPENED)
    )
    assert opened is not None
    assert opened.actor == SIGNAL_AGENT_ACTOR
    assert opened.payload["incident_ref"] == "INC-001"
    assert opened.payload["opportunity_ref"] == "OPP-2001"
    assert opened.payload["severity"] == "high"


def test_every_audit_event_is_attached_to_its_incident(cycled: Session) -> None:
    incident = _the_incident(cycled)
    events = cycled.scalars(
        sa.select(obs_orm.AuditEvent).where(obs_orm.AuditEvent.incident_id == incident.id)
    ).all()

    assert len(events) == 2


def test_a_legal_transition_is_persisted_and_audited(
    cycled: Session, evaluation_timestamp: datetime
) -> None:
    incident = _the_incident(cycled)
    transition_incident(
        cycled,
        incident,
        IncidentStatus.INVESTIGATING,
        actor="system",
        reason="workflow run started",
        occurred_at=evaluation_timestamp + timedelta(minutes=1),
    )
    cycled.expire_all()

    reloaded = _the_incident(cycled)
    assert reloaded.status is IncidentStatus.INVESTIGATING

    audits = cycled.scalar(
        sa.select(sa.func.count())
        .select_from(obs_orm.AuditEvent)
        .where(obs_orm.AuditEvent.event_type == AUDIT_INCIDENT_TRANSITIONED)
    )
    assert audits == 2


def test_an_illegal_transition_is_rejected(cycled: Session, evaluation_timestamp: datetime) -> None:
    """Acceptance criterion 6. TRIAGED cannot jump straight to COMPLETED."""
    incident = _the_incident(cycled)

    with pytest.raises(IllegalTransitionError, match="cannot move from triaged"):
        transition_incident(
            cycled,
            incident,
            IncidentStatus.COMPLETED,
            actor="system",
            reason="attempted shortcut",
            occurred_at=evaluation_timestamp,
        )


def test_a_rejected_transition_leaves_no_audit_trace(
    cycled: Session, evaluation_timestamp: datetime
) -> None:
    """A refusal is not an event -- nothing happened."""
    before = cycled.scalar(sa.select(sa.func.count()).select_from(obs_orm.AuditEvent))
    incident = _the_incident(cycled)

    with pytest.raises(IllegalTransitionError):
        transition_incident(
            cycled,
            incident,
            IncidentStatus.COMPLETED,
            actor="system",
            reason="attempted shortcut",
            occurred_at=evaluation_timestamp,
        )

    after = cycled.scalar(sa.select(sa.func.count()).select_from(obs_orm.AuditEvent))
    assert after == before


def test_entering_a_terminal_state_sets_the_closing_timestamp(
    cycled: Session, evaluation_timestamp: datetime
) -> None:
    incident = _the_incident(cycled)
    closed_at = evaluation_timestamp + timedelta(hours=1)

    transition_incident(
        cycled,
        incident,
        IncidentStatus.DISMISSED,
        actor="user:USR-77",
        reason="false positive",
        occurred_at=closed_at,
    )
    cycled.expire_all()

    reloaded = _the_incident(cycled)
    assert reloaded.status is IncidentStatus.DISMISSED
    assert reloaded.closed_at == closed_at


def test_a_terminal_incident_cannot_be_reopened(
    cycled: Session, evaluation_timestamp: datetime
) -> None:
    incident = _the_incident(cycled)
    transition_incident(
        cycled,
        incident,
        IncidentStatus.DISMISSED,
        actor="user:USR-77",
        reason="false positive",
        occurred_at=evaluation_timestamp,
    )

    with pytest.raises(IllegalTransitionError, match="terminal"):
        transition_incident(
            cycled,
            incident,
            IncidentStatus.INVESTIGATING,
            actor="system",
            reason="changed my mind",
            occurred_at=evaluation_timestamp,
        )
