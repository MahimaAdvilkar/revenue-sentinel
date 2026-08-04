"""Incident lifecycle service.

Converts a newly detected signal into an incident, and moves incidents through the
state machine. Every state change writes an `audit_events` row: `incidents.status`
holds the *current* state, so without the audit trail an incident's history would
not exist anywhere.

Incident references come from a PostgreSQL sequence rather than `count(*) + 1`,
which is a race under any concurrency. A sequence does not reuse a number after a
rolled-back transaction, so a failed insert burns one -- allocation therefore
happens *after* the deduplication check, where the insert is expected to succeed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.errors import RevenueSentinelError
from revenue_sentinel.core.ids import PREFIX_INCIDENT, format_ref
from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import events as event_orm
from revenue_sentinel.db.models import gtm as gtm_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.domain.enums import IncidentStatus, IncidentType, SignalType
from revenue_sentinel.incidents.lifecycle import is_terminal, require_legal

INCIDENT_REF_SEQUENCE: Final = "incident_ref_seq"
INCIDENT_REF_WIDTH: Final = 3

SIGNAL_AGENT_ACTOR: Final = "agent:signal_agent"
"""The Signal Agent runs upstream of the graph (docs/agent-architecture.md §1) and
is deterministic. Naming it as the actor keeps the audit trail answerable to
"who did this" rather than to "the system"."""

AUDIT_INCIDENT_OPENED: Final = "incident.opened"
AUDIT_INCIDENT_TRANSITIONED: Final = "incident.transitioned"

# The account name is deliberately absent: CRM opportunity names conventionally
# already lead with it ("Northwind Logistics - Platform Expansion"), so including it
# again produced "Northwind Logistics - Northwind Logistics - Platform Expansion".
# The account is a separate field on every API response and dashboard row.
_TITLE_BY_TYPE: Final[dict[IncidentType, str]] = {
    IncidentType.STALLED_OPPORTUNITY: "{opportunity} stalled at {stage}",
}


class IncidentServiceError(RevenueSentinelError):
    """The service was asked to do something the data does not support."""


@dataclass(frozen=True, slots=True)
class OpenedIncident:
    """An incident that was just created, with the signal that produced it."""

    incident: workflow_orm.Incident
    signal: event_orm.Signal


def allocate_incident_ref(session: Session) -> str:
    """Take the next incident reference: `INC-001`, `INC-002`, ..."""
    number = session.execute(
        sa.select(sa.func.nextval(sa.text(f"'{INCIDENT_REF_SEQUENCE}'")))
    ).scalar_one()
    return format_ref(PREFIX_INCIDENT, int(number), width=INCIDENT_REF_WIDTH)


def record_audit_event(
    session: Session,
    *,
    event_type: str,
    actor: str,
    payload: JSONObject,
    occurred_at: datetime,
    incident_id: object | None = None,
) -> obs_orm.AuditEvent:
    """Append one audit row. Append-only -- never updated, never deleted."""
    audit = obs_orm.AuditEvent(
        run_id=None,
        incident_id=incident_id,
        event_type=event_type,
        actor=actor,
        payload=payload,
        occurred_at=occurred_at,
    )
    session.add(audit)
    session.flush()
    return audit


def build_incident_title(
    *, incident_type: IncidentType, account_name: str, opportunity_name: str, stage: str
) -> str:
    template = _TITLE_BY_TYPE.get(incident_type, "{account} - {opportunity} ({stage})")
    return template.format(account=account_name, opportunity=opportunity_name, stage=stage)


def open_incident_for_signal(
    session: Session, signal: event_orm.Signal, *, occurred_at: datetime
) -> workflow_orm.Incident:
    """Create an incident from a signal, then triage it.

    The incident is created at `DETECTED` and immediately transitioned to `TRIAGED`
    through the state machine, rather than being written straight to `TRIAGED`. That
    costs one extra row and buys two things: the documented lifecycle is actually
    followed on the happy path, and the audit trail records the triage step instead
    of implying it.

    `incidents.signal_id` is UNIQUE, so a second call for the same signal is refused
    by the database rather than by this function.
    """
    opportunity: gtm_orm.Opportunity | None = None
    if signal.opportunity_id is not None:
        opportunity = session.get(gtm_orm.Opportunity, signal.opportunity_id)
    account = session.get(gtm_orm.Account, signal.account_id)

    if account is None:
        raise IncidentServiceError(f"signal {signal.id} references a missing account")
    if opportunity is None:
        raise IncidentServiceError(
            f"signal {signal.id} has no opportunity; v1 incidents are opportunity-scoped"
        )

    incident_type = IncidentType(SignalType(signal.signal_type).value)
    incident = workflow_orm.Incident(
        incident_ref=allocate_incident_ref(session),
        signal_id=signal.id,
        incident_type=incident_type,
        status=IncidentStatus.DETECTED,
        severity=signal.severity,
        account_id=account.id,
        opportunity_id=opportunity.id,
        opened_at=occurred_at,
        closed_at=None,
        title=build_incident_title(
            incident_type=incident_type,
            account_name=account.name,
            opportunity_name=opportunity.name,
            stage=opportunity.stage.value,
        ),
    )
    session.add(incident)
    session.flush()

    record_audit_event(
        session,
        event_type=AUDIT_INCIDENT_OPENED,
        actor=SIGNAL_AGENT_ACTOR,
        payload={
            "incident_ref": incident.incident_ref,
            "signal_type": signal.signal_type.value,
            "detector_version": signal.detector_version,
            "dedupe_key": signal.dedupe_key,
            "opportunity_ref": opportunity.opportunity_ref,
            "account_ref": account.account_ref,
            "severity": signal.severity.value,
        },
        occurred_at=occurred_at,
        incident_id=incident.id,
    )

    transition_incident(
        session,
        incident,
        IncidentStatus.TRIAGED,
        actor=SIGNAL_AGENT_ACTOR,
        reason="severity assigned from weighted pipeline value",
        occurred_at=occurred_at,
    )
    return incident


def transition_incident(
    session: Session,
    incident: workflow_orm.Incident,
    to_status: IncidentStatus,
    *,
    actor: str,
    reason: str,
    occurred_at: datetime,
) -> workflow_orm.Incident:
    """Move an incident along a legal edge, or raise.

    Entering a terminal state sets `closed_at`; the domain model requires it, and
    a terminal incident without a closing timestamp would be an inconsistency the
    dashboard would render as an open incident that cannot be worked.
    """
    from_status = IncidentStatus(incident.status)
    require_legal(incident.incident_ref, from_status, to_status)

    incident.status = to_status
    if is_terminal(to_status):
        incident.closed_at = occurred_at
    session.flush()

    record_audit_event(
        session,
        event_type=AUDIT_INCIDENT_TRANSITIONED,
        actor=actor,
        payload={
            "incident_ref": incident.incident_ref,
            "from_status": from_status.value,
            "to_status": to_status.value,
            "reason": reason,
        },
        occurred_at=occurred_at,
        incident_id=incident.id,
    )
    return incident
