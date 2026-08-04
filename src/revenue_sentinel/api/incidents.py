"""`GET /incidents` and `GET /incidents/{incident_ref}`.

Read-only. Nothing in Session 2 mutates an incident over HTTP -- the only writer is
the ingestion pipeline, and approvals arrive in Session 6.
"""

from __future__ import annotations

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from revenue_sentinel.api.deps import get_session
from revenue_sentinel.api.schemas import (
    AccountSummary,
    ErrorResponse,
    IncidentDetail,
    IncidentListResponse,
    IncidentSummary,
    OpportunitySummary,
    SignalSummary,
)
from revenue_sentinel.db.models import events as event_orm
from revenue_sentinel.db.models import gtm as gtm_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.domain.enums import IncidentStatus, Severity

router = APIRouter(tags=["incidents"])


def _summarize(
    incident: workflow_orm.Incident,
    account: gtm_orm.Account,
    opportunity: gtm_orm.Opportunity | None,
) -> IncidentSummary:
    return IncidentSummary(
        incident_ref=incident.incident_ref,
        incident_type=incident.incident_type,
        status=incident.status,
        severity=incident.severity,
        title=incident.title,
        opened_at=incident.opened_at,
        closed_at=incident.closed_at,
        account_ref=account.account_ref,
        opportunity_ref=opportunity.opportunity_ref if opportunity else None,
    )


@router.get(
    "/incidents",
    response_model=IncidentListResponse,
    summary="List incidents, newest first",
)
def list_incidents(
    session: Annotated[Session, Depends(get_session)],
    incident_status: Annotated[
        IncidentStatus | None, Query(alias="status", description="Filter by lifecycle status")
    ] = None,
    severity: Annotated[Severity | None, Query(description="Filter by severity")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> IncidentListResponse:
    """The incident queue.

    Ordered by `opened_at` descending then `incident_ref`, so the ordering is total
    even when several incidents share an instant -- which they do, because the
    evaluation timestamp is frozen.
    """
    query = sa.select(workflow_orm.Incident)
    if incident_status is not None:
        query = query.where(workflow_orm.Incident.status == incident_status)
    if severity is not None:
        query = query.where(workflow_orm.Incident.severity == severity)

    rows = session.scalars(
        query.order_by(
            workflow_orm.Incident.opened_at.desc(), workflow_orm.Incident.incident_ref
        ).limit(limit)
    ).all()

    summaries: list[IncidentSummary] = []
    for incident in rows:
        account = session.get(gtm_orm.Account, incident.account_id)
        if account is None:
            continue
        opportunity = (
            session.get(gtm_orm.Opportunity, incident.opportunity_id)
            if incident.opportunity_id is not None
            else None
        )
        summaries.append(_summarize(incident, account, opportunity))

    return IncidentListResponse(count=len(summaries), incidents=tuple(summaries))


@router.get(
    "/incidents/{incident_ref}",
    response_model=IncidentDetail,
    responses={404: {"model": ErrorResponse, "description": "No such incident"}},
    summary="One incident, with the signal that produced it",
)
def get_incident(
    incident_ref: str,
    session: Annotated[Session, Depends(get_session)],
) -> IncidentDetail:
    """Fetch an incident by its business reference, e.g. `INC-001`."""
    incident = session.scalar(
        sa.select(workflow_orm.Incident).where(workflow_orm.Incident.incident_ref == incident_ref)
    )
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"incident not found: {incident_ref}",
        )

    account = session.get(gtm_orm.Account, incident.account_id)
    signal = session.get(event_orm.Signal, incident.signal_id)
    if account is None or signal is None:
        # Both are non-null foreign keys, so this is unreachable via the schema.
        # Raising rather than returning a half-populated record keeps the wire
        # contract honest if it ever becomes reachable.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"incident {incident_ref} references missing records",
        )

    opportunity = (
        session.get(gtm_orm.Opportunity, incident.opportunity_id)
        if incident.opportunity_id is not None
        else None
    )

    return IncidentDetail(
        incident_ref=incident.incident_ref,
        incident_type=incident.incident_type,
        status=incident.status,
        severity=incident.severity,
        title=incident.title,
        opened_at=incident.opened_at,
        closed_at=incident.closed_at,
        account=AccountSummary(
            account_ref=account.account_ref,
            name=account.name,
            segment=account.segment.value,
            is_simulated=account.is_simulated,
        ),
        opportunity=(
            OpportunitySummary(
                opportunity_ref=opportunity.opportunity_ref,
                name=opportunity.name,
                stage=opportunity.stage,
                amount=opportunity.amount,
                currency=opportunity.currency,
                probability=opportunity.probability,
                expected_close_date=opportunity.expected_close_date.isoformat(),
                is_simulated=opportunity.is_simulated,
            )
            if opportunity is not None
            else None
        ),
        signal=SignalSummary(
            signal_type=signal.signal_type,
            detector_version=signal.detector_version,
            severity=signal.severity,
            detected_at=signal.detected_at,
            dedupe_key=signal.dedupe_key,
            evidence_event_count=len(signal.evidence_refs or []),
        ),
    )
