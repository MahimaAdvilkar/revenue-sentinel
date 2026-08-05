"""Running an investigation.

Assembles state, runs the graph, persists what it produced, and advances the
incident. The graph itself knows none of this -- it receives services and returns
state, which is what ADR-0002 means by orchestration owning topology and nothing else.

The whole run happens inside the caller's transaction. If citation validation rejects
a fabricated reference, the exception propagates and the transaction rolls back:
**no evidence, no hypotheses, and no impact assessment are left behind.** A partially
persisted investigation would be worse than none, because it would look complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.analytics.windows import days_since_last_sales_touch, week_over_week_growth
from revenue_sentinel.core.config import Settings
from revenue_sentinel.core.errors import (
    CalculationError,
    NotFoundError,
    RevenueSentinelError,
)
from revenue_sentinel.core.ids import new_id
from revenue_sentinel.core.logging import get_logger
from revenue_sentinel.db.models import gtm as gtm_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.db.repositories import AccountRepository, OpportunityRepository
from revenue_sentinel.domain.enums import SALES_TOUCH_TYPES, IncidentStatus, WorkflowStatus
from revenue_sentinel.domain.gtm import Account, Opportunity
from revenue_sentinel.domain.incidents import Incident
from revenue_sentinel.incidents.service import transition_incident
from revenue_sentinel.intelligence.factory import build_llm_client
from revenue_sentinel.orchestration.evidence_source import RepositoryEvidenceSource
from revenue_sentinel.orchestration.graph import GRAPH_VERSION, build_graph
from revenue_sentinel.orchestration.nodes import IMPACT_NODE, NodeContext
from revenue_sentinel.orchestration.persistence import PersistedInvestigation, persist_investigation
from revenue_sentinel.orchestration.state import WorkflowState
from revenue_sentinel.orchestration.transitions import GRAPH_EXIT_NODE, TransitionRecorder

logger = get_logger(__name__)

INVESTIGATOR_ACTOR = "agent:investigation_graph"

INVESTIGABLE_STATUS = IncidentStatus.TRIAGED
"""An investigation starts from `TRIAGED`. Re-investigating an incident that has
already been analysed is a *replay*, which is Session 6 work -- so it is refused here
with an explanation rather than half-attempted."""


class IncidentNotInvestigableError(RevenueSentinelError):
    """The incident is not in a state an investigation can start from."""

    def __init__(self, incident_ref: str, status: IncidentStatus) -> None:
        self.incident_ref = incident_ref
        self.status = status
        super().__init__(
            f"{incident_ref} is {status.value}; an investigation starts from "
            f"{INVESTIGABLE_STATUS.value}. Re-running an investigation is replay, which "
            f"arrives in Session 6. To run the demo again: make seed && make ingest."
        )


@dataclass(frozen=True, slots=True)
class InvestigationOutcome:
    """What one investigation produced."""

    run_id: object
    incident_ref: str
    state: WorkflowState
    persisted: PersistedInvestigation
    transitions: int


def _load_incident(session: Session, incident_ref: str) -> workflow_orm.Incident:
    incident = session.scalar(
        sa.select(workflow_orm.Incident).where(workflow_orm.Incident.incident_ref == incident_ref)
    )
    if incident is None:
        raise NotFoundError("incident", incident_ref)
    return incident


def _window_inputs(
    session: Session, account: Account, opportunity: Opportunity, evaluated_at: datetime
) -> tuple[int, Decimal]:
    """Days of sales silence and week-over-week usage growth.

    Both come from `analytics/windows.py` -- the same functions the detector used, so
    the investigation cannot disagree with the signal that opened it.
    """
    latest_touch = session.scalar(
        sa.select(sa.func.max(gtm_orm.Activity.occurred_at)).where(
            gtm_orm.Activity.opportunity_id == opportunity.id,
            gtm_orm.Activity.activity_type.in_(list(SALES_TOUCH_TYPES)),
        )
    )
    days_inactive = days_since_last_sales_touch(
        latest_sales_touch=latest_touch, evaluated_at=evaluated_at
    )
    if days_inactive is None:
        raise CalculationError(
            f"{opportunity.opportunity_ref} has no recorded sales touch; "
            f"an incident should not have opened for it"
        )

    snapshots = session.scalars(
        sa.select(gtm_orm.UsageSnapshot)
        .where(gtm_orm.UsageSnapshot.account_id == account.id)
        .order_by(gtm_orm.UsageSnapshot.period_start)
    ).all()
    if len(snapshots) < 2:
        raise CalculationError(f"{account.account_ref} has fewer than two usage snapshots")

    growth = week_over_week_growth(
        earlier=snapshots[-2].feature_events, later=snapshots[-1].feature_events
    )
    return days_inactive, growth


def run_investigation(
    session: Session, incident_ref: str, *, settings: Settings
) -> InvestigationOutcome:
    """Investigate one incident, end to end."""
    incident_row = _load_incident(session, incident_ref)
    incident = Incident.model_validate(incident_row)
    if incident.status is not INVESTIGABLE_STATUS:
        raise IncidentNotInvestigableError(incident_ref, incident.status)

    account = AccountRepository(session).get_by_id(incident.account_id)
    if account is None:
        raise NotFoundError("account", str(incident.account_id))
    if incident.opportunity_id is None:
        raise NotFoundError("opportunity", f"{incident_ref} has no opportunity")
    opportunity = OpportunityRepository(session).get_by_id(incident.opportunity_id)
    if opportunity is None:
        raise NotFoundError("opportunity", str(incident.opportunity_id))

    evaluated_at = settings.evaluation_timestamp
    days_inactive, growth = _window_inputs(session, account, opportunity, evaluated_at)

    run = workflow_orm.WorkflowRun(
        id=new_id(),
        incident_id=incident.id,
        graph_version=GRAPH_VERSION,
        status=WorkflowStatus.RUNNING,
        current_node=None,
        started_at=evaluated_at,
    )
    session.add(run)
    session.flush()

    transition_incident(
        session,
        incident_row,
        IncidentStatus.INVESTIGATING,
        actor=INVESTIGATOR_ACTOR,
        reason=f"workflow run {run.id} started",
        occurred_at=evaluated_at,
    )

    initial = WorkflowState(
        run_id=run.id,
        incident_id=incident.id,
        incident=incident,
        account=account,
        opportunity=opportunity,
        evaluated_at=evaluated_at,
        days_inactive=days_inactive,
        usage_growth=str(growth),
    )

    recorder = TransitionRecorder(session=session, run_id=run.id, occurred_at=evaluated_at)
    context = NodeContext(
        llm=build_llm_client(settings),
        evidence_source=RepositoryEvidenceSource(session),
        model_id=settings.model_default,
        effort=settings.model_effort_default,
    )
    graph = build_graph(session, recorder, context)

    result = graph.invoke({"state": initial}, config={"configurable": {"thread_id": str(run.id)}})
    final: WorkflowState = result["state"]

    # The exit transition: recorded after the last node, completing the chain.
    recorder.record(from_node=IMPACT_NODE, to_node=GRAPH_EXIT_NODE, state_digest=final.digest())

    persisted = persist_investigation(session, final, occurred_at=evaluated_at)

    run.status = WorkflowStatus.COMPLETED
    run.current_node = GRAPH_EXIT_NODE
    run.ended_at = evaluated_at
    session.flush()

    transition_incident(
        session,
        incident_row,
        IncidentStatus.ANALYZED,
        actor=INVESTIGATOR_ACTOR,
        reason="hypotheses and deterministic impact complete",
        occurred_at=evaluated_at,
    )

    logger.info(
        "investigation_complete",
        incident_ref=incident_ref,
        run_id=str(run.id),
        evidence_items=persisted.evidence_items,
        hypotheses=persisted.hypotheses,
        transitions=recorder.next_sequence,
    )

    return InvestigationOutcome(
        run_id=run.id,
        incident_ref=incident_ref,
        state=final,
        persisted=persisted,
        transitions=recorder.next_sequence,
    )
