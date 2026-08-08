"""Execution: idempotency, refusal, retry, and the honest unknown.

Session 6 built these guarantees; this module is where they stop being claims. Every
"never" below is checked against a **counting client** rather than inferred from a
returned error, because "the adapter was not called" and "the call returned an error" are
different facts and only one of them is the guarantee.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.core.ids import new_id
from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import investigation as orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import (
    ActionStatus,
    ActionType,
    ApprovalStatus,
    PolicyDecision,
    ProposedAction,
    RiskTier,
    ToolCallStatus,
)
from revenue_sentinel.execution import executor, retry
from revenue_sentinel.execution.authorization import (
    ApprovalMissingError,
    PolicyDeniedExecutionError,
    PolicyDriftError,
    authorize_execution,
)
from revenue_sentinel.execution.idempotency import idempotency_key
from revenue_sentinel.execution.service import run_execution_phase
from revenue_sentinel.governance import approvals, tiers
from revenue_sentinel.governance.outcomes import PolicyOutcome
from revenue_sentinel.mcp.errors import ToolErrorCode
from revenue_sentinel.orchestration import runner

APPROVER = "usr:revenue-lead"
REQUESTER = "agent:policy_and_risk"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class CountingClient:
    """Wraps a real MCP client and counts what actually reached it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def call_tool(self, tool_name: str, arguments: JSONObject) -> JSONObject:
        self.calls.append(tool_name)
        return self._inner.call_tool(tool_name, arguments)  # type: ignore[no-any-return]

    def list_tools(self) -> list[JSONObject]:
        return self._inner.list_tools()  # type: ignore[no-any-return]

    def with_policy(self, engine: object) -> CountingClient:
        """Rebind the wrapped client but keep counting through this one."""
        rebound = CountingClient(self._inner.with_policy(engine))
        rebound.calls = self.calls
        return rebound


class ScriptedClient:
    """Returns a fixed sequence of envelopes. Never touches an adapter."""

    def __init__(self, *payloads: JSONObject) -> None:
        self._payloads = list(payloads)
        self.calls: list[str] = []

    def call_tool(self, tool_name: str, arguments: JSONObject) -> JSONObject:
        self.calls.append(tool_name)
        index = min(len(self.calls) - 1, len(self._payloads) - 1)
        return self._payloads[index]

    def list_tools(self) -> list[JSONObject]:
        return []


def error_envelope(code: ToolErrorCode) -> JSONObject:
    return {
        "tool": "crm_create_task",
        "ok": False,
        "integration_status": "SIMULATED",
        "error": {"code": code.value, "message": "scripted", "retry": True},
    }


SUCCESS_ENVELOPE: JSONObject = {
    "tool": "crm_create_task",
    "ok": True,
    "integration_status": "SIMULATED",
    "data": {"task_ref": "TSK-1"},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def execution_client(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> CountingClient:
    return CountingClient(
        runner._execution_client(
            detected, run_id=investigated.run_id, evaluated_at=settings.evaluation_timestamp
        )
    )


def intervention_by_decision(
    session: Session, run_id: UUID, decision: PolicyDecision
) -> orm.Intervention:
    row = session.scalar(
        sa.select(orm.Intervention)
        .join(
            gov_orm.PolicyEvaluation,
            gov_orm.PolicyEvaluation.intervention_id == orm.Intervention.id,
        )
        .where(orm.Intervention.run_id == run_id, gov_orm.PolicyEvaluation.decision == decision)
    )
    assert row is not None, f"the golden run should contain a {decision.value} intervention"
    return row


def action_records(session: Session, run_id: UUID) -> list[gov_orm.ActionRecord]:
    return list(
        session.scalars(
            sa.select(gov_orm.ActionRecord).where(gov_orm.ActionRecord.run_id == run_id)
        ).all()
    )


# ---------------------------------------------------------------------------
# A. Idempotency
# ---------------------------------------------------------------------------
def test_the_first_execution_creates_exactly_one_action_record(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    records = action_records(detected, investigated.run_id)

    assert len(records) == 1
    assert records[0].action_type is ActionType.CRM_TASK
    assert records[0].status is ActionStatus.SUCCEEDED
    assert (records[0].result or {}).get("integration_status") == "SIMULATED"


def test_re_running_execution_creates_no_new_action_records_and_calls_no_adapter(
    investigated: runner.InvestigationOutcome,
    detected: Session,
    settings: Settings,
    execution_client: CountingClient,
) -> None:
    """The whole point of the claimed key: a second pass is provably a no-op."""
    before = len(action_records(detected, investigated.run_id))

    phase = run_execution_phase(
        detected,
        run_id=investigated.run_id,
        incident_ref="INC-001",
        client=execution_client,
        occurred_at=settings.evaluation_timestamp,
    )

    assert len(action_records(detected, investigated.run_id)) == before
    assert execution_client.calls == [], "the adapter was reached on a re-run"
    assert phase.performed == ()
    assert all(item.already_done for item in phase.executed)


def test_a_re_run_returns_the_stored_result_rather_than_recomputing(
    investigated: runner.InvestigationOutcome,
    detected: Session,
    settings: Settings,
    execution_client: CountingClient,
) -> None:
    stored = action_records(detected, investigated.run_id)[0].result or {}

    phase = run_execution_phase(
        detected,
        run_id=investigated.run_id,
        incident_ref="INC-001",
        client=execution_client,
        occurred_at=settings.evaluation_timestamp,
    )

    assert phase.executed[0].payload == stored
    assert phase.executed[0].status is ActionStatus.SUCCEEDED


def test_the_key_ignores_the_run_and_therefore_survives_a_second_run() -> None:
    """`run_id` is deliberately absent: the key identifies an *effect*, not an attempt.

    Keyed by run, a second investigation of the same incident would compute a different
    key and cheerfully create a second draft -- the exact failure this design prevents.
    """
    arguments: JSONObject = {"opportunity_ref": "OPP-2001", "title": "Book a review"}
    first = idempotency_key(
        incident_ref="INC-001",
        action_type=ActionType.CRM_TASK,
        target_ref="OPP-2001",
        arguments=arguments,
    )
    second = idempotency_key(
        incident_ref="INC-001",
        action_type=ActionType.CRM_TASK,
        target_ref="OPP-2001",
        arguments=dict(reversed(list(arguments.items()))),
    )

    assert first == second, "argument ordering must not change the key"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("incident_ref", "INC-002"),
        ("target_ref", "OPP-9999"),
        ("arguments", {"opportunity_ref": "OPP-2001", "title": "Something else"}),
        ("action_type", ActionType.EMAIL_DRAFT),
    ],
)
def test_changing_a_real_business_input_changes_the_key(field: str, value: object) -> None:
    """A different effect must get a different key, or the second one silently vanishes."""
    base = {
        "incident_ref": "INC-001",
        "action_type": ActionType.CRM_TASK,
        "target_ref": "OPP-2001",
        "arguments": {"opportunity_ref": "OPP-2001", "title": "Book a review"},
    }
    changed = {**base, field: value}

    assert idempotency_key(**base) != idempotency_key(**changed)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# B. INDETERMINATE -- the honest unknown
# ---------------------------------------------------------------------------
def test_a_claim_stuck_in_executing_becomes_indeterminate_and_calls_nothing(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> None:
    """The process died between claiming the effect and recording it.

    The effect may or may not have happened. Retrying could duplicate a real email;
    marking it failed could hide one. Neither guess is made (ADR-0017).
    """
    record = action_records(detected, investigated.run_id)[0]
    record.status = ActionStatus.EXECUTING
    detected.flush()

    client = ScriptedClient(SUCCESS_ENVELOPE)
    phase = run_execution_phase(
        detected,
        run_id=investigated.run_id,
        incident_ref="INC-001",
        client=client,
        occurred_at=settings.evaluation_timestamp,
    )

    detected.refresh(record)
    assert record.status is ActionStatus.INDETERMINATE
    assert client.calls == [], "an ambiguous claim must not be retried"
    assert phase.performed == ()
    assert len(action_records(detected, investigated.run_id)) == 1


def test_indeterminate_is_a_real_status_rather_than_a_synonym_for_failed() -> None:
    """If it collapsed into FAILED, "we do not know" would be indistinguishable from
    "it definitely did not happen" -- which is the claim we decline to make."""
    assert ActionStatus.INDETERMINATE is not ActionStatus.FAILED
    assert ActionStatus.INDETERMINATE is not ActionStatus.SUCCEEDED
    assert ActionStatus.INDETERMINATE.value == "indeterminate"


# ---------------------------------------------------------------------------
# C. Policy drift -- fail closed
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("drifted", [PolicyDecision.DENY, PolicyDecision.REQUIRE_APPROVAL])
def test_execution_fails_closed_when_the_rules_have_changed(
    drifted: PolicyDecision,
    investigated: runner.InvestigationOutcome,
    detected: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stored decision is a record of what was decided, not authority for now."""
    allowed = intervention_by_decision(detected, investigated.run_id, PolicyDecision.ALLOW)

    def drifted_evaluate(_request: object) -> PolicyOutcome:
        return PolicyOutcome(
            decision=drifted,
            risk_tier=RiskTier.CUSTOMER_FACING_OR_MATERIAL,
            policy_version="policy/v2-drifted",
            matched_rules=("test:drift",),
            reason="the rules changed since this was decided",
        )

    monkeypatch.setattr("revenue_sentinel.execution.authorization.evaluate", drifted_evaluate)

    with pytest.raises(PolicyDriftError, match="rule set nobody checked"):
        authorize_execution(detected, allowed.id, now=settings.evaluation_timestamp)


def test_a_drifted_decision_never_reaches_an_adapter(
    investigated: runner.InvestigationOutcome,
    detected: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(_request: object) -> PolicyOutcome:
        return PolicyOutcome(
            decision=PolicyDecision.DENY,
            risk_tier=RiskTier.PROHIBITED,
            policy_version="policy/v2-drifted",
            matched_rules=("test:drift",),
            reason="drifted",
        )

    monkeypatch.setattr("revenue_sentinel.execution.authorization.evaluate", denied)
    client = ScriptedClient(SUCCESS_ENVELOPE)

    phase = run_execution_phase(
        detected,
        run_id=investigated.run_id,
        incident_ref="INC-001",
        client=client,
        occurred_at=settings.evaluation_timestamp,
    )

    assert client.calls == []
    assert phase.performed == ()


# ---------------------------------------------------------------------------
# D. A forged approval cannot override a denial
# ---------------------------------------------------------------------------
def test_an_approved_request_cannot_authorise_a_denied_action(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> None:
    """The nastiest attack this layer must survive: a real, APPROVED row on a DENY.

    It fails because the code that reads approvals is unreachable for a denied action --
    structural, not a rule somebody remembered to write.
    """
    denied = intervention_by_decision(detected, investigated.run_id, PolicyDecision.DENY)
    evaluation = detected.scalar(
        sa.select(gov_orm.PolicyEvaluation).where(
            gov_orm.PolicyEvaluation.intervention_id == denied.id
        )
    )
    assert evaluation is not None

    forged = gov_orm.ApprovalRequest(
        id=new_id(),
        approval_ref="APR-999",
        policy_evaluation_id=evaluation.id,
        run_id=investigated.run_id,
        status=ApprovalStatus.APPROVED,
        requested_by="attacker",
        requested_at=settings.evaluation_timestamp,
        expires_at=settings.evaluation_timestamp + timedelta(days=365),
        decided_at=settings.evaluation_timestamp,
        decided_by="attacker",
        decision_note="forged",
    )
    detected.add(forged)
    detected.flush()

    with pytest.raises(PolicyDeniedExecutionError, match="cannot override a denial"):
        authorize_execution(detected, denied.id, now=settings.evaluation_timestamp)


def test_the_denied_action_never_produces_an_action_record_or_an_adapter_call(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> None:
    denied = intervention_by_decision(detected, investigated.run_id, PolicyDecision.DENY)
    client = ScriptedClient(SUCCESS_ENVELOPE)

    run_execution_phase(
        detected,
        run_id=investigated.run_id,
        incident_ref="INC-001",
        client=client,
        occurred_at=settings.evaluation_timestamp,
    )

    for record in action_records(detected, investigated.run_id):
        assert record.intervention_id != denied.id
    assert client.calls == []


def test_a_prohibited_action_has_no_executable_representation() -> None:
    """The cheapest of the four guarantees: there is nowhere to write it."""
    executable = {member.value for member in ActionType}

    assert ProposedAction.SEND_EMAIL_DIRECT.value not in executable
    assert ProposedAction.RECORD_DELETE.value not in executable


# ---------------------------------------------------------------------------
# E. Approval behaviour
# ---------------------------------------------------------------------------
def approval_for_pending(session: Session, run_id: UUID) -> gov_orm.ApprovalRequest:
    request = session.scalar(
        sa.select(gov_orm.ApprovalRequest).where(gov_orm.ApprovalRequest.run_id == run_id)
    )
    assert request is not None
    return request


@pytest.mark.parametrize(
    "status", [ApprovalStatus.PENDING, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED]
)
def test_a_non_approved_request_blocks_execution(
    status: ApprovalStatus,
    investigated: runner.InvestigationOutcome,
    detected: Session,
    settings: Settings,
) -> None:
    request = approval_for_pending(detected, investigated.run_id)
    request.status = status
    detected.flush()

    approval_needed = intervention_by_decision(
        detected, investigated.run_id, PolicyDecision.REQUIRE_APPROVAL
    )

    with pytest.raises(ApprovalMissingError):
        authorize_execution(detected, approval_needed.id, now=settings.evaluation_timestamp)


def test_a_pending_request_past_its_expiry_blocks_without_a_sweeper(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> None:
    """Expiry is evaluated on read, so the gap before cleanup is not a gap in control.

    The row stays `PENDING` in the database; only the *reading* of it changes. A test
    that mutated the stored status would prove the sweeper works, not the guarantee.
    """
    request = approval_for_pending(detected, investigated.run_id)
    assert request.status is ApprovalStatus.PENDING

    approval_needed = intervention_by_decision(
        detected, investigated.run_id, PolicyDecision.REQUIRE_APPROVAL
    )
    after_expiry = request.expires_at + timedelta(seconds=1)

    with pytest.raises(ApprovalMissingError, match="expired"):
        authorize_execution(detected, approval_needed.id, now=after_expiry)

    detected.refresh(request)
    assert request.status is ApprovalStatus.PENDING


def test_an_approved_tier_two_action_creates_exactly_one_email_draft(
    investigated: runner.InvestigationOutcome,
    detected: Session,
    settings: Settings,
    execution_client: CountingClient,
) -> None:
    request = approval_for_pending(detected, investigated.run_id)
    approvals.decide(
        detected,
        request,
        approved=True,
        decided_by=APPROVER,
        occurred_at=settings.evaluation_timestamp,
    )

    phase = run_execution_phase(
        detected,
        run_id=investigated.run_id,
        incident_ref="INC-001",
        client=execution_client,
        occurred_at=settings.evaluation_timestamp,
    )

    drafts = [
        record
        for record in action_records(detected, investigated.run_id)
        if record.action_type is ActionType.EMAIL_DRAFT
    ]
    assert len(drafts) == 1
    assert drafts[0].status is ActionStatus.SUCCEEDED
    assert drafts[0].approval_request_id == request.id
    assert execution_client.calls == ["messaging_create_email_draft"]
    assert phase.is_complete


def test_the_requester_cannot_self_approve(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> None:
    """Compared against the real `requested_by` column as of migration 0005."""
    request = approval_for_pending(detected, investigated.run_id)
    assert request.requested_by == REQUESTER

    with pytest.raises(approvals.SelfApprovalError):
        approvals.decide(
            detected,
            request,
            approved=True,
            decided_by=REQUESTER,
            occurred_at=settings.evaluation_timestamp,
        )


def test_a_slack_notification_authorises_nothing(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> None:
    """Notification and authorisation are different systems that happen to be adjacent.

    A successful `messaging_send_slack_approval` tool call is recorded in `tool_calls`
    and is read by nothing in the authorisation path.
    """
    detected.add(
        obs_orm.ToolCall(
            id=new_id(),
            run_id=investigated.run_id,
            node_name="notify",
            tool_name="messaging_send_slack_approval",
            args={"channel_ref": "#revenue-ops"},
            result_digest="x" * 64,
            status=ToolCallStatus.SUCCESS,
            duration_ms=1,
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id=None,
        )
    )
    request = approval_for_pending(detected, investigated.run_id)
    request.status = ApprovalStatus.PENDING
    detected.flush()

    approval_needed = intervention_by_decision(
        detected, investigated.run_id, PolicyDecision.REQUIRE_APPROVAL
    )

    with pytest.raises(ApprovalMissingError, match="not an approval"):
        authorize_execution(detected, approval_needed.id, now=settings.evaluation_timestamp)


# ---------------------------------------------------------------------------
# F. Retry
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code", sorted(retry.RETRYABLE_BY_EXECUTOR, key=lambda c: c.value))
def test_a_transient_failure_is_retried_to_the_maximum(
    code: ToolErrorCode,
    investigated: runner.InvestigationOutcome,
    detected: Session,
    settings: Settings,
) -> None:
    allowed = intervention_by_decision(detected, investigated.run_id, PolicyDecision.ALLOW)
    grant = authorize_execution(detected, allowed.id, now=settings.evaluation_timestamp)
    client = ScriptedClient(error_envelope(code))
    slept: list[float] = []

    result = executor.execute(
        detected,
        replace(grant, intervention_id=allowed.id),
        client=client,
        incident_ref="INC-RETRY",
        run_id=investigated.run_id,
        arguments={"probe": code.value},
        occurred_at=settings.evaluation_timestamp,
        sleep=slept.append,
    )

    assert len(client.calls) == retry.MAX_ATTEMPTS
    assert result.attempts == retry.MAX_ATTEMPTS
    assert result.status is ActionStatus.FAILED

    record = detected.get(gov_orm.ActionRecord, result.action_record_id)
    assert record is not None
    assert record.attempt_count == retry.MAX_ATTEMPTS
    # Backoff runs between attempts, never after the last one.
    assert slept == [0.05, 0.10]


@pytest.mark.parametrize(
    "code",
    [
        ToolErrorCode.INVALID_ARGUMENTS,
        ToolErrorCode.NOT_FOUND,
        ToolErrorCode.POLICY_DENIED,
        ToolErrorCode.APPROVAL_REQUIRED,
        ToolErrorCode.BUDGET_EXCEEDED,
    ],
)
def test_a_non_transient_failure_is_never_retried(
    code: ToolErrorCode,
    investigated: runner.InvestigationOutcome,
    detected: Session,
    settings: Settings,
) -> None:
    allowed = intervention_by_decision(detected, investigated.run_id, PolicyDecision.ALLOW)
    grant = authorize_execution(detected, allowed.id, now=settings.evaluation_timestamp)
    client = ScriptedClient(error_envelope(code))
    slept: list[float] = []

    result = executor.execute(
        detected,
        grant,
        client=client,
        incident_ref=f"INC-{code.value}",
        run_id=investigated.run_id,
        arguments={"probe": code.value},
        occurred_at=settings.evaluation_timestamp,
        sleep=slept.append,
    )

    assert len(client.calls) == 1
    assert result.attempts == 1
    assert result.status is ActionStatus.FAILED
    assert slept == [], "a non-transient failure must not wait before giving up"


def test_the_executor_retry_set_is_deliberately_narrower_than_the_agent_guidance() -> None:
    """`ERROR_POLICY[...].retry` is *agent* guidance and must not be reused here.

    `INVALID_ARGUMENTS` tells an agent to fix its arguments and try again. An executor's
    arguments come from a persisted intervention, so re-sending them unchanged would
    reproduce the identical failure until the attempt limit -- which is why the two
    notions of "retryable" are separate rather than shared.
    """
    from revenue_sentinel.mcp.errors import ERROR_POLICY

    agent_retryable = {code for code, policy in ERROR_POLICY.items() if policy.retry}

    assert agent_retryable > retry.RETRYABLE_BY_EXECUTOR
    assert ToolErrorCode.INVALID_ARGUMENTS in agent_retryable
    assert ToolErrorCode.INVALID_ARGUMENTS not in retry.RETRYABLE_BY_EXECUTOR


def test_backoff_is_deterministic_and_doubling() -> None:
    assert [retry.backoff_ms(attempt) for attempt in (1, 2, 3)] == [50, 100, 200]
    assert retry.backoff_ms(1) == retry.backoff_ms(1)

    with pytest.raises(ValueError, match="1-based"):
        retry.backoff_ms(0)


def test_a_retried_call_writes_one_tool_call_row_per_attempt(
    investigated: runner.InvestigationOutcome,
    detected: Session,
    settings: Settings,
    execution_client: CountingClient,
) -> None:
    """Retries are visible in the ledger rather than hidden inside one row."""
    before = detected.scalar(sa.select(sa.func.count()).select_from(obs_orm.ToolCall))
    request = approval_for_pending(detected, investigated.run_id)
    approvals.decide(
        detected,
        request,
        approved=True,
        decided_by=APPROVER,
        occurred_at=settings.evaluation_timestamp,
    )

    run_execution_phase(
        detected,
        run_id=investigated.run_id,
        incident_ref="INC-001",
        client=execution_client,
        occurred_at=settings.evaluation_timestamp,
    )

    after = detected.scalar(sa.select(sa.func.count()).select_from(obs_orm.ToolCall))
    assert after is not None and before is not None
    assert after - before == len(execution_client.calls)


def test_the_material_field_set_is_still_the_documented_one() -> None:
    """Guards the drift test above from becoming vacuous if the tier table moves."""
    assert tiers.MATERIAL_OPPORTUNITY_FIELDS
    assert tiers.POLICY_VERSION == "policy/v1"
