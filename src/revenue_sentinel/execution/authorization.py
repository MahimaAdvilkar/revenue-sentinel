"""The one door to execution.

Nothing else in this codebase may build an `ActionRecord`. Every effect that leaves the
process passes through `authorize_execution` first, and it either returns a grant or
raises -- it never returns without an answer.

**Policy is re-evaluated here, from scratch.** The stored `policy_evaluations` row is
treated as a record of what was decided, not as authority for what may happen now. Rules
can change between a decision and its execution, and an executor that trusted the stored
decision would be executing under a rule set nobody checked. A disagreement is a
`PolicyDriftError`, not a shrug.

**Approval is consulted only when the fresh decision is `REQUIRE_APPROVAL`.** That is
what makes "an approval can never override a denial" structural rather than a rule
somebody remembers: for a denied action, the code that reads approvals is unreachable.

**A Slack notification is not an approval.** Nothing here reads `tool_calls`, and the
only thing that authorises a Tier 2 action is an `ApprovalRequest` row whose effective
status is `APPROVED`. Notification and authorisation are different systems that happen to
be adjacent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.errors import RevenueSentinelError
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import investigation as orm
from revenue_sentinel.domain.enums import (
    ActionType,
    ApprovalStatus,
    PolicyDecision,
    ProposedAction,
)
from revenue_sentinel.governance import approvals
from revenue_sentinel.governance.outcomes import PolicyOutcome
from revenue_sentinel.governance.policy_engine import PolicyRequest, evaluate


class ExecutionRefusedError(RevenueSentinelError):
    """Base for every reason an action may not run. Always specific in practice."""


class PolicyDeniedExecutionError(ExecutionRefusedError):
    def __init__(self, intervention_ref: str, reason: str) -> None:
        super().__init__(
            f"{intervention_ref} is denied by policy and cannot be executed. {reason} "
            f"An approval cannot override a denial."
        )


class ApprovalMissingError(ExecutionRefusedError):
    def __init__(self, intervention_ref: str, status: ApprovalStatus | None) -> None:
        state = status.value if status is not None else "no approval request exists"
        super().__init__(
            f"{intervention_ref} requires human approval before it can run ({state}). "
            f"A Slack notification is not an approval."
        )


class PolicyDriftError(ExecutionRefusedError):
    """The stored decision and a fresh evaluation disagree."""

    def __init__(self, intervention_ref: str, stored: str, fresh: str) -> None:
        super().__init__(
            f"{intervention_ref} was recorded as {stored} but evaluates to {fresh} now. "
            f"Refusing to execute under a rule set nobody checked. Re-run the "
            f"investigation, or reconcile the policy version."
        )


class NotExecutableError(ExecutionRefusedError):
    """The proposed action has no executable counterpart, by construction."""

    def __init__(self, action: ProposedAction) -> None:
        super().__init__(
            f"{action.value} is not an executable action type. Prohibited actions have "
            f"no member in ActionType and therefore no representation in action_records."
        )


@dataclass(frozen=True, slots=True)
class ExecutionGrant:
    """Permission to perform exactly one effect, with its paper trail attached."""

    intervention_id: UUID
    action_type: ActionType
    target_ref: str
    outcome: PolicyOutcome
    policy_evaluation_id: UUID
    approval_request_id: UUID | None


def executable_action(action: ProposedAction) -> ActionType | None:
    """The `ActionType` counterpart of a proposed action, if one exists.

    Returns `None` for tier-3 members. They are absent from `ActionType` on purpose:
    a prohibited action has nowhere to be written even if every other check were
    bypassed.
    """
    try:
        return ActionType(action.value)
    except ValueError:
        return None


def authorize_execution(
    session: Session, intervention_id: UUID, *, now: datetime
) -> ExecutionGrant:
    """Decide whether this intervention may run **now**. Raises if it may not."""
    intervention = session.get(orm.Intervention, intervention_id)
    if intervention is None:
        raise ExecutionRefusedError(f"intervention {intervention_id} does not exist")

    evaluation = session.scalar(
        sa.select(gov_orm.PolicyEvaluation).where(
            gov_orm.PolicyEvaluation.intervention_id == intervention_id
        )
    )
    if evaluation is None:
        raise ExecutionRefusedError(
            f"{intervention.title!r} has no policy evaluation. An action with no "
            f"recorded decision cannot be executed."
        )

    fresh = evaluate(
        PolicyRequest(
            action=intervention.action_type,
            target_ref=intervention.target_ref,
            fields_changed=frozenset(),
            actor="agent:execution",
        )
    )

    if fresh.decision is not evaluation.decision:
        raise PolicyDriftError(intervention.title, evaluation.decision.value, fresh.decision.value)

    if fresh.decision is PolicyDecision.DENY:
        raise PolicyDeniedExecutionError(intervention.title, fresh.reason)

    approval_id: UUID | None = None
    if fresh.decision is PolicyDecision.REQUIRE_APPROVAL:
        approval_id = _require_approval(session, intervention.title, evaluation.id, now=now)

    action_type = executable_action(intervention.action_type)
    if action_type is None:
        # Unreachable while DENY covers every tier-3 member, and kept anyway: it is the
        # backstop if a future tier-3 action were ever mapped to a permissive decision.
        raise NotExecutableError(intervention.action_type)

    return ExecutionGrant(
        intervention_id=intervention_id,
        action_type=action_type,
        target_ref=intervention.target_ref,
        outcome=fresh,
        policy_evaluation_id=evaluation.id,
        approval_request_id=approval_id,
    )


def _require_approval(
    session: Session, intervention_ref: str, policy_evaluation_id: UUID, *, now: datetime
) -> UUID:
    request = session.scalar(
        sa.select(gov_orm.ApprovalRequest).where(
            gov_orm.ApprovalRequest.policy_evaluation_id == policy_evaluation_id
        )
    )
    if request is None:
        raise ApprovalMissingError(intervention_ref, None)

    status = approvals.effective_status(request, now=now)
    if status is not ApprovalStatus.APPROVED:
        raise ApprovalMissingError(intervention_ref, status)

    return request.id
