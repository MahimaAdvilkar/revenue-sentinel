"""The read surface the dashboard needs.

**Every route here is a GET.** No mutation endpoint ships in Session 9, and that is a
decision rather than an omission (ADR-0022): approvals are a *claimed* identity with no
authentication behind them, so an `Approve` button in a browser would imply a session, a
user, and accountability that do not exist. The CLI is honest about running as whoever
holds the shell; a button would not be. The approval inbox therefore renders the exact
command to run, and the decision stays where it can be described truthfully.

Routes stay thin (rule 6): parse, delegate, serialize. Every one of these delegates to a
service built in an earlier session -- `cost.summary`, `cost.timeline`,
`approval_service`, `evaluation.service` -- so this module adds a transport, not
behaviour.

Money and cost serialize as **strings at full precision**. A dashboard that rendered
`$0.000000` as `0.0` would undo the reason `cost_entries.amount_usd` has six decimal
places, and JSON floats cannot carry `Decimal` faithfully.
"""

from __future__ import annotations

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from revenue_sentinel.api.deps import get_session
from revenue_sentinel.api.schemas import (
    ApprovalInboxItem,
    ApprovalInboxResponse,
    CostLedgerEntry,
    CostSummaryResponse,
    ErrorResponse,
    EvaluationResponse,
    EvaluationResultItem,
    EvidenceItemView,
    HypothesisView,
    ImpactView,
    InterventionView,
    InvestigationResponse,
    OverviewResponse,
    TimelineEventView,
    TimelineResponse,
)
from revenue_sentinel.core.config import get_settings
from revenue_sentinel.cost import reporting as cost_reporting
from revenue_sentinel.cost.summary import summarise_run
from revenue_sentinel.cost.timeline import incident_timeline, traces_in
from revenue_sentinel.db.models import evaluation as eval_orm
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import investigation as inv_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.domain.enums import TERMINAL_INCIDENT_STATUSES, IncidentStatus
from revenue_sentinel.governance import approval_service

router = APIRouter(tags=["dashboard"])

SIMULATED: Annotated[str, "Rendered from data, never hardcoded in the UI"] = "SIMULATED"

NOT_FOUND: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}
}


def _run_id(session: Session, incident_ref: str) -> object:
    from revenue_sentinel.core.errors import NotFoundError

    try:
        return cost_reporting.latest_run_id(session, incident_ref)
    except NotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no completed run for {incident_ref}",
        ) from error


@router.get("/overview", response_model=OverviewResponse)
def overview(session: Annotated[Session, Depends(get_session)]) -> OverviewResponse:
    """What is at risk, in dollars, right now."""
    at_risk = session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(inv_orm.ImpactAssessment.at_risk_value), 0))
    )
    weighted = session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(inv_orm.ImpactAssessment.weighted_value), 0))
    )
    rows = session.execute(
        sa.select(workflow_orm.Incident.status, sa.func.count()).group_by(
            workflow_orm.Incident.status
        )
    ).all()

    counts = {str(row[0].value): int(row[1]) for row in rows}
    open_incidents = sum(
        value
        for key, value in counts.items()
        if IncidentStatus(key) not in TERMINAL_INCIDENT_STATUSES
    )

    return OverviewResponse(
        total_at_risk=str(at_risk or 0),
        total_weighted=str(weighted or 0),
        open_incidents=open_incidents,
        incidents_by_status=counts,
        integration_status=SIMULATED,
    )


@router.get(
    "/incidents/{incident_ref}/investigation",
    response_model=InvestigationResponse,
    responses=NOT_FOUND,
)
def investigation(
    incident_ref: str, session: Annotated[Session, Depends(get_session)]
) -> InvestigationResponse:
    """Evidence, hypotheses and the deterministic impact figures."""
    run_id = _run_id(session, incident_ref)

    evidence = session.scalars(
        sa.select(inv_orm.EvidenceItem)
        .where(inv_orm.EvidenceItem.run_id == run_id)
        .order_by(inv_orm.EvidenceItem.evidence_ref)
    ).all()
    hypotheses = session.scalars(
        sa.select(inv_orm.Hypothesis)
        .where(inv_orm.Hypothesis.run_id == run_id)
        .order_by(inv_orm.Hypothesis.rank)
    ).all()
    impact = session.scalar(
        sa.select(inv_orm.ImpactAssessment).where(inv_orm.ImpactAssessment.run_id == run_id)
    )

    cited: dict[str, list[str]] = {}
    for hypothesis in hypotheses:
        refs = session.scalars(
            sa.select(inv_orm.EvidenceItem.evidence_ref)
            .join(
                inv_orm.HypothesisEvidence,
                inv_orm.HypothesisEvidence.evidence_item_id == inv_orm.EvidenceItem.id,
            )
            .where(inv_orm.HypothesisEvidence.hypothesis_id == hypothesis.id)
            .order_by(inv_orm.EvidenceItem.evidence_ref)
        ).all()
        cited[hypothesis.hypothesis_ref] = list(refs)

    return InvestigationResponse(
        incident_ref=incident_ref,
        evidence=[
            EvidenceItemView(
                evidence_ref=item.evidence_ref,
                source_system=item.source_system.value,
                tool_name=item.tool_name,
                trust_level=item.trust_level.value,
                content=item.content,
                integration_status=SIMULATED,
            )
            for item in evidence
        ],
        hypotheses=[
            HypothesisView(
                hypothesis_ref=item.hypothesis_ref,
                statement=item.statement,
                confidence=str(item.confidence),
                rank=item.rank,
                cites=cited.get(item.hypothesis_ref, []),
            )
            for item in hypotheses
        ],
        impact=None
        if impact is None
        else ImpactView(
            pipeline_value=str(impact.pipeline_value),
            weighted_value=str(impact.weighted_value),
            at_risk_value=str(impact.at_risk_value),
            currency=impact.currency,
            computed_by=impact.computed_by.value,
            method_version=impact.method_version,
        ),
    )


@router.get(
    "/incidents/{incident_ref}/interventions",
    response_model=list[InterventionView],
    responses=NOT_FOUND,
)
def interventions(
    incident_ref: str, session: Annotated[Session, Depends(get_session)]
) -> list[InterventionView]:
    """Ranked interventions with the decision and the rules behind it."""
    run_id = _run_id(session, incident_ref)

    rows = session.scalars(
        sa.select(inv_orm.Intervention)
        .where(inv_orm.Intervention.run_id == run_id)
        .order_by(inv_orm.Intervention.rank)
    ).all()

    views: list[InterventionView] = []
    for row in rows:
        evaluation = session.scalar(
            sa.select(gov_orm.PolicyEvaluation).where(
                gov_orm.PolicyEvaluation.intervention_id == row.id
            )
        )
        action = session.scalar(
            sa.select(gov_orm.ActionRecord).where(gov_orm.ActionRecord.intervention_id == row.id)
        )
        views.append(
            InterventionView(
                rank=row.rank,
                title=row.title,
                action_type=row.action_type.value,
                rationale=row.rationale,
                target_ref=row.target_ref,
                expected_value=str(row.expected_value),
                composite_score=str(row.composite_score),
                decision=None if evaluation is None else evaluation.decision.value,
                risk_tier=None if evaluation is None else int(evaluation.risk_tier),
                matched_rules=[] if evaluation is None else list(evaluation.matched_rules),
                reason=None if evaluation is None else evaluation.reason,
                executed=action is not None,
                action_status=None if action is None else action.status.value,
                integration_status=SIMULATED,
            )
        )
    return views


@router.get(
    "/incidents/{incident_ref}/timeline", response_model=TimelineResponse, responses=NOT_FOUND
)
def timeline(
    incident_ref: str, session: Annotated[Session, Depends(get_session)]
) -> TimelineResponse:
    """The trace-correlated merge. Absent tracing metadata stays absent."""
    run_id = _run_id(session, incident_ref)
    events = incident_timeline(session, run_id=run_id)  # type: ignore[arg-type]

    return TimelineResponse(
        incident_ref=incident_ref,
        trace_count=len(traces_in(events)),
        events=[
            TimelineEventView(
                occurred_at=event.occurred_at,
                source=event.source,
                event_type=event.event_type,
                detail=event.detail,
                trace_id=event.trace_id,
                span_id=event.span_id,
                parent_span_id=event.parent_span_id,
                amount_usd=None if event.amount_usd is None else str(event.amount_usd),
                pricing_version=event.pricing_version,
                integration_status=event.integration_status,
            )
            for event in events
        ],
    )


@router.get(
    "/incidents/{incident_ref}/cost", response_model=CostSummaryResponse, responses=NOT_FOUND
)
def cost(
    incident_ref: str, session: Annotated[Session, Depends(get_session)]
) -> CostSummaryResponse:
    """Microdollar precision throughout -- `$0.000000` is not rounded to `$0.00`."""
    run_id = _run_id(session, incident_ref)
    summary = summarise_run(session, run_id=run_id, incident_ref=incident_ref)  # type: ignore[arg-type]

    entries = session.scalars(
        sa.select(obs_orm.CostEntry)
        .where(obs_orm.CostEntry.run_id == run_id)
        .order_by(obs_orm.CostEntry.recorded_at, obs_orm.CostEntry.cost_type)
    ).all()

    return CostSummaryResponse(
        incident_ref=incident_ref,
        model_cost=str(summary.model_cost),
        tool_cost=str(summary.tool_cost),
        total_cost=str(summary.total_cost),
        model_calls=summary.model_calls,
        tool_calls=summary.tool_calls,
        pricing_versions=list(summary.pricing_versions),
        concurrency_note=(
            "Budgets are checked read-then-call and are safe only because model calls "
            "are serialized within a run. Two concurrent runs sharing a GLOBAL budget "
            "can race (ADR-0019)."
        ),
        ledger=[
            CostLedgerEntry(
                kind="model" if entry.model_call_id is not None else "tool",
                cost_type=entry.cost_type.value,
                amount_usd=str(entry.amount_usd),
                pricing_version=entry.pricing_version,
            )
            for entry in entries
        ],
    )


@router.get("/approvals", response_model=ApprovalInboxResponse)
def approvals(session: Annotated[Session, Depends(get_session)]) -> ApprovalInboxResponse:
    """The inbox. **Read-only** -- it renders the command, it does not run it.

    There is no authentication in this system, so a browser button would imply a session
    and an accountable user that do not exist (ADR-0018, ADR-0022).
    """
    settings = get_settings()
    views = approval_service.list_requests(
        session, now=settings.evaluation_timestamp, pending_only=True
    )

    return ApprovalInboxResponse(
        pending=[
            ApprovalInboxItem(
                approval_ref=view.approval_ref,
                status=view.effective_status.value,
                requested_by=view.requested_by,
                expires_at=view.expires_at,
                intervention_title=view.intervention_title,
                approve_command=(f"uv run rs approve {view.approval_ref} --as usr:your-name"),
                integration_status=SIMULATED,
            )
            for view in views
        ],
        identity_note=(
            "Approval is available on the CLI only. `--as` is a CLAIMED identity, not an "
            "authenticated one: this system has no authentication (ADR-0018)."
        ),
    )


@router.get("/evaluation/latest", response_model=EvaluationResponse, responses=NOT_FOUND)
def evaluation(session: Annotated[Session, Depends(get_session)]) -> EvaluationResponse:
    """The most recent evaluation attempt. History is append-only, so this is a view of
    one attempt rather than a mutable status."""
    run = session.scalar(
        sa.select(eval_orm.EvaluationRun).order_by(eval_orm.EvaluationRun.started_at.desc())
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no evaluation has been run; try `make eval`",
        )

    results = session.scalars(
        sa.select(eval_orm.EvaluationResult)
        .where(eval_orm.EvaluationResult.evaluation_run_id == run.id)
        .order_by(eval_orm.EvaluationResult.check_name)
    ).all()

    return EvaluationResponse(
        suite_name=run.suite_name,
        evaluator_version=run.suite_version,
        passed=run.passed,
        total=run.total,
        llm_judge_used=False,
        evaluation_cost="0.000000",
        results=[
            EvaluationResultItem(
                check_name=item.check_name,
                outcome=item.outcome.value,
                expected=item.expected,
                actual=item.actual,
                detail=item.detail,
            )
            for item in results
        ],
    )
