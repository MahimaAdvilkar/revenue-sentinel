"""The execution phase: run what is authorised, pause for what is not.

One pass over the ranked interventions. Each one is authorised independently and lands in
exactly one bucket:

* **executed** -- `ALLOW`, performed now
* **awaiting approval** -- `REQUIRE_APPROVAL` with no approved request. The phase stops
  being able to finish, and the run is marked `INTERRUPTED`
* **refused** -- `DENY`, or an approval that was rejected or expired. Recorded, never
  attempted

**The pause is a property of our own tables, not of the graph framework.** A run is
resumable because `interventions`, `policy_evaluations`, `approval_requests` and
`action_records` are all committed before the pause -- so resuming is a fresh process
reading durable rows, which is why it survives a restart with nothing in memory. The
LangGraph checkpointer (ADR-0016) makes the *graph* resumable; this makes the *work*
resumable, and the second is the one the business cares about.

Resuming is just running this function again. It is safe to call any number of times:
every effect is idempotency-claimed, so a completed action returns its stored result and
performs nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.logging import get_logger
from revenue_sentinel.db.models import investigation as orm
from revenue_sentinel.db.repositories import AccountRepository, OpportunityRepository
from revenue_sentinel.domain.enums import ActionStatus
from revenue_sentinel.execution.arguments import build_arguments
from revenue_sentinel.execution.authorization import (
    ApprovalMissingError,
    ExecutionGrant,
    ExecutionRefusedError,
    authorize_execution,
)
from revenue_sentinel.execution.executor import TOOL_FOR_ACTION, ExecutionResult, execute
from revenue_sentinel.execution.policy_binding import ApprovedActionPolicyEngine
from revenue_sentinel.execution.retry import SleepFn, no_sleep
from revenue_sentinel.mcp.client import McpClient

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RefusedAction:
    """An intervention that was not executed, and the reason in a sentence."""

    title: str
    reason: str
    awaiting_approval: bool


@dataclass(slots=True)
class ExecutionPhase:
    """What one pass over the interventions did."""

    executed: list[ExecutionResult] = field(default_factory=list)
    refused: list[RefusedAction] = field(default_factory=list)

    @property
    def awaiting_approval(self) -> tuple[RefusedAction, ...]:
        return tuple(item for item in self.refused if item.awaiting_approval)

    @property
    def is_complete(self) -> bool:
        """No intervention is still waiting on a person."""
        return not self.awaiting_approval

    @property
    def performed(self) -> tuple[ExecutionResult, ...]:
        """Effects performed *this pass*. Empty on an idempotent re-run."""
        return tuple(item for item in self.executed if not item.already_done)


def run_execution_phase(
    session: Session,
    *,
    run_id: UUID,
    incident_ref: str,
    client: McpClient,
    occurred_at: datetime,
    sleep: SleepFn = no_sleep,
) -> ExecutionPhase:
    """Execute everything currently authorised. Safe to call repeatedly."""
    interventions = session.scalars(
        sa.select(orm.Intervention)
        .where(orm.Intervention.run_id == run_id)
        .order_by(orm.Intervention.rank)
    ).all()

    phase = ExecutionPhase()
    for intervention in interventions:
        _process(
            session,
            intervention,
            phase=phase,
            run_id=run_id,
            incident_ref=incident_ref,
            client=client,
            occurred_at=occurred_at,
            sleep=sleep,
        )
    return phase


def _process(
    session: Session,
    intervention: orm.Intervention,
    *,
    phase: ExecutionPhase,
    run_id: UUID,
    incident_ref: str,
    client: McpClient,
    occurred_at: datetime,
    sleep: SleepFn,
) -> None:
    try:
        grant = authorize_execution(session, intervention.id, now=occurred_at)
    except ApprovalMissingError as refusal:
        phase.refused.append(
            RefusedAction(intervention.title, str(refusal), awaiting_approval=True)
        )
        return
    except ExecutionRefusedError as refusal:
        # A denial is a normal outcome, not an error condition. It is recorded and the
        # phase carries on -- one refused proposal must not abandon the approved ones.
        phase.refused.append(
            RefusedAction(intervention.title, str(refusal), awaiting_approval=False)
        )
        return

    account = AccountRepository(session).get_by_id(_account_id(session, run_id))
    opportunity = OpportunityRepository(session).get_by_id(_opportunity_id(session, run_id))
    if account is None or opportunity is None:  # pragma: no cover -- FKs make this unreachable
        raise ExecutionRefusedError(f"{intervention.title!r} has no account or opportunity")

    result = execute(
        session,
        grant,
        client=_client_for(client, grant),
        incident_ref=incident_ref,
        run_id=run_id,
        arguments=build_arguments(
            intervention,
            action_type=grant.action_type,
            account=account,
            opportunity=opportunity,
            incident_ref=incident_ref,
            occurred_at=occurred_at,
        ),
        occurred_at=occurred_at,
        sleep=sleep,
    )
    phase.executed.append(result)

    logger.info(
        "action_executed" if not result.already_done else "action_already_done",
        intervention=intervention.title,
        action_type=grant.action_type.value,
        status=result.status.value,
        attempts=result.attempts,
        integration_status=result.payload.get("integration_status"),
    )


def _client_for(client: McpClient, grant: ExecutionGrant) -> McpClient:
    """Hand the write gate the approval this action already has.

    The gate re-evaluates policy independently -- as it should, since it must never
    trust its caller. Without being shown the recorded approval it answers
    `REQUIRE_APPROVAL` again, and an approved action could never run. Scoped to this one
    tool, and it never converts a denial. See `policy_binding.py`.
    """
    if grant.approval_request_id is None:
        return client

    tool_name = TOOL_FOR_ACTION.get(grant.action_type)
    rebind = getattr(client, "with_policy", None)
    if tool_name is None or rebind is None:
        # A client that cannot be rebound keeps whatever engine it has. Test doubles
        # land here; the real path does not.
        return client

    rebound: McpClient = rebind(
        ApprovedActionPolicyEngine(
            tool_name=tool_name, approval_request_id=grant.approval_request_id
        )
    )
    return rebound


def _account_id(session: Session, run_id: UUID) -> UUID:
    from revenue_sentinel.db.models import workflow as workflow_orm

    return session.execute(
        sa.select(workflow_orm.Incident.account_id)
        .join(
            workflow_orm.WorkflowRun,
            workflow_orm.WorkflowRun.incident_id == workflow_orm.Incident.id,
        )
        .where(workflow_orm.WorkflowRun.id == run_id)
    ).scalar_one()


def _opportunity_id(session: Session, run_id: UUID) -> UUID:
    """An incident without an opportunity never reaches an investigation, let alone an
    execution -- `run_investigation` refuses it long before this point."""
    from revenue_sentinel.db.models import workflow as workflow_orm

    opportunity_id = session.execute(
        sa.select(workflow_orm.Incident.opportunity_id)
        .join(
            workflow_orm.WorkflowRun,
            workflow_orm.WorkflowRun.incident_id == workflow_orm.Incident.id,
        )
        .where(workflow_orm.WorkflowRun.id == run_id)
    ).scalar_one()
    if opportunity_id is None:  # pragma: no cover -- refused upstream by the runner
        raise ExecutionRefusedError(f"run {run_id} has no opportunity to act on")
    return opportunity_id


def summarise(phase: ExecutionPhase) -> str:
    """A line for the CLI. Mentions SIMULATED because every result is (rule 5)."""
    performed = len(phase.performed)
    already = len(phase.executed) - performed
    waiting = len(phase.awaiting_approval)
    refused = len(phase.refused) - waiting
    succeeded = sum(1 for item in phase.executed if item.status is ActionStatus.SUCCEEDED)

    return (
        f"{performed} performed ({succeeded} succeeded), {already} already done, "
        f"{waiting} awaiting approval, {refused} refused -- all SIMULATED"
    )
