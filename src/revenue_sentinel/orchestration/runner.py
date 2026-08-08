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
from uuid import UUID

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
from revenue_sentinel.execution.service import ExecutionPhase, run_execution_phase
from revenue_sentinel.governance.policy_engine import DeterministicPolicyEngine
from revenue_sentinel.incidents.service import transition_incident
from revenue_sentinel.integrations.simulated.behaviour import SimulatedBehaviour
from revenue_sentinel.intelligence.factory import build_llm_client
from revenue_sentinel.mcp.client import InProcessMcpClient
from revenue_sentinel.mcp.context import ToolContext, build_simulated_adapters
from revenue_sentinel.orchestration.graph import GRAPH_VERSION, build_graph
from revenue_sentinel.orchestration.mcp_evidence_source import McpEvidenceSource
from revenue_sentinel.orchestration.nodes import POLICY_NODE, NodeContext
from revenue_sentinel.orchestration.persistence import PersistedInvestigation, persist_investigation
from revenue_sentinel.orchestration.state import WorkflowState
from revenue_sentinel.orchestration.transitions import GRAPH_EXIT_NODE, TransitionRecorder

logger = get_logger(__name__)

INVESTIGATOR_ACTOR = "agent:investigation_graph"
EXECUTOR_ACTOR = "agent:execution"
EXECUTION_NODE = "execute_actions"

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
    execution: ExecutionPhase
    """What the execution phase did. `execution.is_complete` is `False` when the run is
    paused waiting on a person."""


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

    # Evidence comes through the GTM MCP server. The agents are unchanged -- this is a
    # different implementation behind the same port (ADR-0004 commitment 1).
    #
    # `policy=None` is deliberate. The investigation graph is read-only, and every
    # tool it calls is Tier 0. Binding no policy engine means a write tool invoked
    # from this path would raise rather than execute, so the graph *cannot* perform a
    # write even by accident -- and certainly not under the allow-everything stub.
    tool_context = ToolContext(
        session=session,
        adapters=build_simulated_adapters(session, SimulatedBehaviour()),
        occurred_at=evaluated_at,
        node_name="collect_evidence",
        run_id=run.id,
        policy=None,
    )
    context = NodeContext(
        llm=build_llm_client(settings),
        evidence_source=McpEvidenceSource(InProcessMcpClient(tool_context), session),
        model_id=settings.model_default,
        effort=settings.model_effort_default,
    )
    graph = build_graph(session, recorder, context)

    result = graph.invoke({"state": initial}, config={"configurable": {"thread_id": str(run.id)}})
    final: WorkflowState = result["state"]

    # The exit transition: recorded after the last node, completing the chain.
    recorder.record(from_node=POLICY_NODE, to_node=GRAPH_EXIT_NODE, state_digest=final.digest())

    persisted = persist_investigation(session, final, occurred_at=evaluated_at)

    transition_incident(
        session,
        incident_row,
        IncidentStatus.ANALYZED,
        actor=INVESTIGATOR_ACTOR,
        reason="hypotheses and deterministic impact complete",
        occurred_at=evaluated_at,
    )

    # The execution phase binds the **real** policy engine. The investigation client
    # above still binds none, so the read-only path cannot write even by accident, and
    # the two clients differ in exactly the way their jobs differ.
    execution = _execute_phase(
        session, run_id=run.id, incident_ref=incident_ref, evaluated_at=evaluated_at
    )
    _record_execution_outcome(
        session, run=run, incident_row=incident_row, phase=execution, occurred_at=evaluated_at
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
        execution=execution,
    )


def _execution_client(
    session: Session, *, run_id: UUID, evaluated_at: datetime
) -> InProcessMcpClient:
    """An MCP client that *can* write, because a policy engine is bound to it."""
    return InProcessMcpClient(
        ToolContext(
            session=session,
            adapters=build_simulated_adapters(session, SimulatedBehaviour()),
            occurred_at=evaluated_at,
            node_name=EXECUTION_NODE,
            run_id=run_id,
            policy=DeterministicPolicyEngine(),
        )
    )


def _execute_phase(
    session: Session, *, run_id: UUID, incident_ref: str, evaluated_at: datetime
) -> ExecutionPhase:
    return run_execution_phase(
        session,
        run_id=run_id,
        incident_ref=incident_ref,
        client=_execution_client(session, run_id=run_id, evaluated_at=evaluated_at),
        occurred_at=evaluated_at,
    )


def _record_execution_outcome(
    session: Session,
    *,
    run: workflow_orm.WorkflowRun,
    incident_row: workflow_orm.Incident,
    phase: ExecutionPhase,
    occurred_at: datetime,
) -> None:
    """Advance the run and the incident to match what execution actually achieved.

    The lifecycle is walked, not jumped: `ANALYZED -> STRATEGIZED -> {AWAITING_APPROVAL |
    EXECUTING} -> COMPLETED`. Each hop writes its own audit row, so the timeline reads as
    what happened rather than as a single leap from analysed to done.
    """
    transition_incident(
        session,
        incident_row,
        IncidentStatus.STRATEGIZED,
        actor=EXECUTOR_ACTOR,
        reason="interventions ranked and policy decisions recorded",
        occurred_at=occurred_at,
    )

    if phase.is_complete:
        run.status = WorkflowStatus.COMPLETED
        run.current_node = GRAPH_EXIT_NODE
        run.ended_at = occurred_at
        session.flush()
        transition_incident(
            session,
            incident_row,
            IncidentStatus.EXECUTING,
            actor=EXECUTOR_ACTOR,
            reason=f"{len(phase.executed)} action(s) authorised",
            occurred_at=occurred_at,
        )
        transition_incident(
            session,
            incident_row,
            IncidentStatus.COMPLETED,
            actor=EXECUTOR_ACTOR,
            reason=f"execution finished: {len(phase.performed)} performed this pass",
            occurred_at=occurred_at,
        )
        return

    # Paused. Everything needed to resume is already committed -- that is what makes a
    # restart survivable, rather than anything held in memory.
    run.status = WorkflowStatus.INTERRUPTED
    run.current_node = EXECUTION_NODE
    session.flush()
    transition_incident(
        session,
        incident_row,
        IncidentStatus.AWAITING_APPROVAL,
        actor=EXECUTOR_ACTOR,
        reason=f"{len(phase.awaiting_approval)} action(s) require human approval",
        occurred_at=occurred_at,
    )


def _record_resume_outcome(
    session: Session,
    *,
    run: workflow_orm.WorkflowRun,
    incident_row: workflow_orm.Incident,
    phase: ExecutionPhase,
    occurred_at: datetime,
) -> None:
    """Advance a *paused* run. It is already `AWAITING_APPROVAL`, so the walk starts there.

    Still waiting? Nothing moves -- re-recording the same status would add an audit row
    saying nothing happened, which is worse than silence.

    Already finished? Also nothing. Resuming a completed run is a legitimate no-op (the
    idempotency claims make it harmless), but the incident is in a terminal state and
    the lifecycle rightly refuses to leave one. Advancing it again would turn a safe
    repeat into an `IllegalTransitionError`.
    """
    if not phase.is_complete or run.status is WorkflowStatus.COMPLETED:
        return

    run.status = WorkflowStatus.COMPLETED
    run.current_node = GRAPH_EXIT_NODE
    run.ended_at = occurred_at
    session.flush()
    transition_incident(
        session,
        incident_row,
        IncidentStatus.EXECUTING,
        actor=EXECUTOR_ACTOR,
        reason="approval granted; remaining actions authorised",
        occurred_at=occurred_at,
    )
    transition_incident(
        session,
        incident_row,
        IncidentStatus.COMPLETED,
        actor=EXECUTOR_ACTOR,
        reason=f"execution finished: {len(phase.performed)} performed this pass",
        occurred_at=occurred_at,
    )


def resume_investigation(
    session: Session, incident_ref: str, *, settings: Settings
) -> ExecutionPhase:
    """Run the execution phase again for a paused run.

    This is *resume*, not replay: no node re-runs, no model is called, and no evidence or
    hypothesis is regenerated. It re-reads durable rows and executes whatever has become
    authorised since the pause. Calling it on a run that needs nothing is a no-op.
    """
    incident_row = _load_incident(session, incident_ref)
    run = session.scalar(
        sa.select(workflow_orm.WorkflowRun)
        .where(workflow_orm.WorkflowRun.incident_id == incident_row.id)
        .order_by(workflow_orm.WorkflowRun.started_at.desc())
    )
    if run is None:
        raise NotFoundError("workflow run", incident_ref)

    evaluated_at = settings.evaluation_timestamp
    phase = _execute_phase(
        session, run_id=run.id, incident_ref=incident_ref, evaluated_at=evaluated_at
    )
    _record_resume_outcome(
        session, run=run, incident_row=incident_row, phase=phase, occurred_at=evaluated_at
    )

    logger.info(
        "execution_resumed",
        incident_ref=incident_ref,
        run_id=str(run.id),
        performed=len(phase.performed),
        awaiting_approval=len(phase.awaiting_approval),
    )
    return phase
