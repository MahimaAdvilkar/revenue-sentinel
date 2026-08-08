"""Approvals, and the golden scenario's three policy outcomes.

The headline assertion is at the bottom: one run of the investigation produces exactly
one ALLOW, one REQUIRE_APPROVAL, and one DENY -- and **nothing executes**. That last
part is checked directly rather than assumed, because "we decided but did not act" is
the claim Session 5 actually makes.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import investigation as orm
from revenue_sentinel.domain.enums import (
    ActionStatus,
    ActionType,
    ApprovalStatus,
    PolicyDecision,
    ProposedAction,
)
from revenue_sentinel.governance import approvals
from revenue_sentinel.orchestration import runner

REQUESTER = "agent:policy_and_risk"
APPROVER = "usr:revenue-lead"


# ---------------------------------------------------------------------------
# Approval requests
# ---------------------------------------------------------------------------
@pytest.fixture
def approval(
    investigated: runner.InvestigationOutcome, detected: Session
) -> gov_orm.ApprovalRequest:
    """The approval request the golden run created."""
    request = detected.scalar(
        sa.select(gov_orm.ApprovalRequest).where(
            gov_orm.ApprovalRequest.run_id == investigated.run_id
        )
    )
    assert request is not None, "the golden run should have produced one approval request"
    return request


def test_an_approval_request_expires_after_its_ttl(
    approval: gov_orm.ApprovalRequest, settings: Settings
) -> None:
    assert approval.expires_at == approval.requested_at + approvals.DEFAULT_APPROVAL_TTL
    assert approval.status is ApprovalStatus.PENDING


def test_a_lapsed_request_reads_as_expired_before_any_sweeper_runs(
    approval: gov_orm.ApprovalRequest,
) -> None:
    """The window between expiry and cleanup must not be a window of authority."""
    just_before = approval.expires_at - timedelta(seconds=1)
    just_after = approval.expires_at

    assert approvals.effective_status(approval, now=just_before) is ApprovalStatus.PENDING
    assert approvals.effective_status(approval, now=just_after) is ApprovalStatus.EXPIRED
    # The stored value has not been touched -- the guarantee is in the read, not in a job.
    assert approval.status is ApprovalStatus.PENDING


def test_self_approval_is_refused(approval: gov_orm.ApprovalRequest, detected: Session) -> None:
    """The actor that asked cannot be the actor that decides."""
    assert approval.requested_by == REQUESTER

    with pytest.raises(approvals.SelfApprovalError):
        approvals.decide(
            detected,
            approval,
            approved=True,
            decided_by=REQUESTER,
            occurred_at=approval.requested_at,
        )

    assert approval.status is ApprovalStatus.PENDING


def test_a_different_actor_may_approve(
    approval: gov_orm.ApprovalRequest, detected: Session
) -> None:
    decided = approvals.decide(
        detected,
        approval,
        approved=True,
        decided_by=APPROVER,
        occurred_at=approval.requested_at,
    )

    assert decided.status is ApprovalStatus.APPROVED
    assert decided.decided_by == APPROVER
    assert decided.decided_at == approval.requested_at


def test_a_rejection_is_recorded_as_such(
    approval: gov_orm.ApprovalRequest, detected: Session
) -> None:
    decided = approvals.decide(
        detected,
        approval,
        approved=False,
        decided_by=APPROVER,
        occurred_at=approval.requested_at,
    )

    assert decided.status is ApprovalStatus.REJECTED


def test_a_lapsed_request_cannot_be_approved(
    approval: gov_orm.ApprovalRequest, detected: Session
) -> None:
    with pytest.raises(approvals.ApprovalExpiredError):
        approvals.decide(
            detected,
            approval,
            approved=True,
            decided_by=APPROVER,
            occurred_at=approval.expires_at + timedelta(seconds=1),
        )

    assert approval.status is ApprovalStatus.EXPIRED


def test_expiring_lapsed_requests_is_idempotent(
    approval: gov_orm.ApprovalRequest, detected: Session
) -> None:
    after = approval.expires_at + timedelta(hours=1)

    assert approvals.expire_lapsed(detected, now=after) == 1
    assert approvals.expire_lapsed(detected, now=after) == 0
    assert approval.status is ApprovalStatus.EXPIRED


# ---------------------------------------------------------------------------
# The golden scenario
# ---------------------------------------------------------------------------
def test_the_golden_run_produces_three_ranked_interventions(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    rows = detected.scalars(
        sa.select(orm.Intervention)
        .where(orm.Intervention.run_id == investigated.run_id)
        .order_by(orm.Intervention.rank)
    ).all()

    assert len(rows) == 3
    assert [row.rank for row in rows] == [1, 2, 3]
    # Descending composite: the order is the scorer's, not the model's.
    scores = [row.composite_score for row in rows]
    assert scores == sorted(scores, reverse=True)


def test_the_lowest_scoring_draft_was_dropped_by_the_scorer(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """The model offered four; three were kept. Which three is `analytics/`'s call.

    If this ever passes vacuously -- because the model happened to offer exactly three
    -- the ranking would be untested in the only way that matters.
    """
    titles = set(
        detected.scalars(
            sa.select(orm.Intervention.title).where(orm.Intervention.run_id == investigated.run_id)
        ).all()
    )

    assert len(investigated.state.interventions) == 3
    assert "Flag the stalled deal to the deal desk in Slack" not in titles


def test_the_golden_run_yields_one_allow_one_approval_and_one_denial(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """Session 5's headline acceptance criterion."""
    decisions = detected.scalars(
        sa.select(gov_orm.PolicyEvaluation.decision)
        .join(orm.Intervention, orm.Intervention.id == gov_orm.PolicyEvaluation.intervention_id)
        .where(orm.Intervention.run_id == investigated.run_id)
    ).all()

    assert sorted(decision.value for decision in decisions) == [
        PolicyDecision.ALLOW.value,
        PolicyDecision.DENY.value,
        PolicyDecision.REQUIRE_APPROVAL.value,
    ]


def test_the_denied_intervention_is_persisted_rather_than_dropped(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """A refusal that left no row would be indistinguishable from a proposal never made."""
    denied = detected.scalar(
        sa.select(orm.Intervention)
        .join(
            gov_orm.PolicyEvaluation,
            gov_orm.PolicyEvaluation.intervention_id == orm.Intervention.id,
        )
        .where(
            orm.Intervention.run_id == investigated.run_id,
            gov_orm.PolicyEvaluation.decision == PolicyDecision.DENY,
        )
    )

    assert denied is not None
    assert denied.action_type is ProposedAction.SEND_EMAIL_DIRECT


def test_every_decision_records_its_rules_and_a_readable_reason(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    rows = detected.scalars(
        sa.select(gov_orm.PolicyEvaluation)
        .join(orm.Intervention, orm.Intervention.id == gov_orm.PolicyEvaluation.intervention_id)
        .where(orm.Intervention.run_id == investigated.run_id)
    ).all()

    assert len(rows) == 3
    for row in rows:
        assert row.matched_rules, "a decision with no matched rules cannot be audited"
        assert row.reason
        assert row.policy_version == "policy/v1"


def test_only_the_approval_tier_creates_an_approval_request(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    requests = detected.scalars(
        sa.select(gov_orm.ApprovalRequest).where(
            gov_orm.ApprovalRequest.run_id == investigated.run_id
        )
    ).all()

    assert len(requests) == 1


# ---------------------------------------------------------------------------
# Nothing executes
# ---------------------------------------------------------------------------
def test_only_the_allowed_action_executed(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """Session 5 asserted nothing executed. Session 6 executes -- but only the ALLOW.

    This assertion **inverted deliberately**, and it is replaced by a stricter set: one
    action record, for the tier-1 task, stamped SIMULATED. The tier-2 draft is still
    waiting on a person and the tier-3 proposal will never run at all.
    """
    records = detected.scalars(
        sa.select(gov_orm.ActionRecord).where(gov_orm.ActionRecord.run_id == investigated.run_id)
    ).all()

    assert len(records) == 1
    assert records[0].action_type is ActionType.CRM_TASK
    assert records[0].status is ActionStatus.SUCCEEDED
    assert (records[0].result or {}).get("integration_status") == "SIMULATED"


def test_the_denied_action_left_no_action_record(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """A denial is recorded as a decision and never as an attempt."""
    executed_types = set(
        detected.scalars(
            sa.select(gov_orm.ActionRecord.action_type).where(
                gov_orm.ActionRecord.run_id == investigated.run_id
            )
        ).all()
    )

    assert ActionType.EMAIL_DRAFT not in executed_types
    assert "send_email_direct" not in {item.value for item in executed_types}


def test_the_run_paused_rather_than_drafting_without_approval(
    investigated: runner.InvestigationOutcome,
) -> None:
    """Nothing is drafted before a person approves it."""
    assert not investigated.execution.is_complete
    assert len(investigated.execution.awaiting_approval) == 1
    assert len(investigated.execution.performed) == 1


def test_every_action_record_traces_to_its_authorisation(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """`authorized_by` is a real foreign key as of migration 0006."""
    record = detected.scalar(
        sa.select(gov_orm.ActionRecord).where(gov_orm.ActionRecord.run_id == investigated.run_id)
    )
    assert record is not None

    evaluation = detected.get(gov_orm.PolicyEvaluation, record.authorized_by)
    assert evaluation is not None
    assert evaluation.decision is PolicyDecision.ALLOW
    # Tier 1 needed no person, so there is no approval attached. That NULL is meaningful.
    assert record.approval_request_id is None


def test_no_tool_call_was_made_by_the_policy_or_strategy_nodes(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """The write tools remain unwired. Neither new node touches MCP at all."""
    from revenue_sentinel.db.models import observability as obs_orm

    nodes = set(
        detected.scalars(
            sa.select(obs_orm.ToolCall.node_name).where(
                obs_orm.ToolCall.run_id == investigated.run_id
            )
        ).all()
    )

    assert "draft_interventions" not in nodes
    assert "evaluate_policy" not in nodes
