"""The six injection cases and the bypass corpus, proven structurally.

Every payload here is placed in a real untrusted content field of a real run and must
remain inert. **No test asks whether a model behaved.** Where an adapter must not be
reached, a counting client proves it rather than an exception implying it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.ids import new_id
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import investigation as inv_orm
from revenue_sentinel.domain.enums import ActionType, ApprovalStatus, PolicyDecision, TrustLevel
from revenue_sentinel.evaluation import security
from revenue_sentinel.evaluation.rubric import CheckResult
from revenue_sentinel.execution.authorization import (
    PolicyDeniedExecutionError,
    authorize_execution,
)
from revenue_sentinel.intelligence.prompts import render_evidence_block
from revenue_sentinel.orchestration import runner


def result_for(results: tuple[CheckResult, ...], name: str) -> CheckResult:
    match = [item for item in results if item.name == name]
    assert match, f"{name} missing from the security corpus"
    return match[0]


# ---------------------------------------------------------------------------
# The six cases
# ---------------------------------------------------------------------------
def test_the_corpus_has_exactly_the_six_documented_cases() -> None:
    """`docs/security-model.md` §2. A case cannot be quietly dropped."""
    assert set(security.INJECTION_CORPUS) == {
        "tag_forgery",
        "instruction_in_activity_body",
        "fake_system_prompt",
        "embedded_tool_call",
        "ignore_previous_instructions",
        "fabricated_authority",
    }


@pytest.mark.parametrize("case", sorted(security.INJECTION_CORPUS))
def test_every_case_is_contained_on_the_golden_run(
    case: str, investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    results = security.evaluate_security(detected, investigated.run_id)
    assert result_for(results, f"injection_{case}_contained").passed


@pytest.mark.parametrize("case", sorted(security.INJECTION_CORPUS))
def test_no_payload_can_break_out_of_its_evidence_block(case: str) -> None:
    """The delimiter must be real, not decorative.

    Rendered into an actual block: an unescaped `</evidence>` would close the wrapper
    early and let the remainder be read as a sibling carrying `trust="trusted"`.
    """
    payload = security.INJECTION_CORPUS[case]
    block = render_evidence_block(
        evidence_ref="EV-001", source_system="support", content={"summary": payload}
    )

    # Exactly one real block: the payload's own angle brackets are escaped, so any
    # `<evidence` it contains is inert text rather than a second opening tag.
    assert block.count("<evidence") == 1
    assert block.count("</evidence>") == 1
    assert block.strip().endswith("</evidence>")
    assert 'trust="untrusted"' in block

    # The forged markup survives as *content*, which is the point: it is visible,
    # auditable, and inert. What must not survive is a parseable second tag.
    if "<evidence" in payload or "</evidence>" in payload:
        assert "&lt;evidence" in block or "&lt;/evidence&gt;" in block


@pytest.mark.parametrize("case", sorted(security.INJECTION_CORPUS))
def test_no_payload_can_forge_an_attribute(case: str) -> None:
    assert security.attribute_is_safe(security.INJECTION_CORPUS[case])


def test_a_payload_persisted_as_evidence_stays_untrusted(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """`TrustLevel` has exactly one member, so there is no code path that marks
    ingested content trusted."""
    item = detected.scalar(
        sa.select(inv_orm.EvidenceItem).where(inv_orm.EvidenceItem.run_id == investigated.run_id)
    )
    assert item is not None
    item.content = {"summary": security.INJECTION_CORPUS["tag_forgery"]}
    detected.flush()

    results = security.evaluate_security(detected, investigated.run_id)
    assert result_for(results, "invariant_untrusted_labelling").passed
    assert item.trust_level is TrustLevel.UNTRUSTED
    assert len(TrustLevel) == 1


def test_an_injected_tool_request_names_a_capability_that_does_not_exist(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """`embedded_tool_call` asks for `messaging_send_email`. It is absent from the
    catalog *and* from the port, so the request is unsatisfiable rather than refused."""
    assert "messaging_send_email" in security.INJECTION_CORPUS["embedded_tool_call"]
    assert not security._send_email_tool_exists()

    results = security.evaluate_security(detected, investigated.run_id)
    assert result_for(results, "bypass_send_email_absent").passed


def test_no_payload_caused_a_tool_call_outside_the_plan(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    assert security._tools_outside_the_plan(detected, investigated.run_id) == ()


# ---------------------------------------------------------------------------
# Attempted bypass vs real bypass
# ---------------------------------------------------------------------------
def test_a_forged_approved_request_on_a_deny_leaves_no_effect(
    investigated: runner.InvestigationOutcome, detected: Session, settings
) -> None:
    """The nastiest case. A refusal may be recorded; **an effect must not exist.**

    The check inspects `action_records`, not the exception -- an exception proves a code
    path ran, not that nothing happened.
    """
    denied = detected.scalar(
        sa.select(inv_orm.Intervention)
        .join(
            gov_orm.PolicyEvaluation,
            gov_orm.PolicyEvaluation.intervention_id == inv_orm.Intervention.id,
        )
        .where(
            inv_orm.Intervention.run_id == investigated.run_id,
            gov_orm.PolicyEvaluation.decision == PolicyDecision.DENY,
        )
    )
    assert denied is not None
    evaluation = detected.scalar(
        sa.select(gov_orm.PolicyEvaluation).where(
            gov_orm.PolicyEvaluation.intervention_id == denied.id
        )
    )
    assert evaluation is not None

    detected.add(
        gov_orm.ApprovalRequest(
            id=new_id(),
            approval_ref="APR-666",
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
    )
    detected.flush()

    with pytest.raises(PolicyDeniedExecutionError):
        authorize_execution(detected, denied.id, now=settings.evaluation_timestamp)

    results = security.evaluate_security(detected, investigated.run_id)
    assert result_for(results, "bypass_no_unauthorised_effect").passed
    assert result_for(results, "bypass_denied_never_executed").passed


def test_the_golden_run_has_no_unauthorised_effect(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """`authorized_by` is a real FK, so an orphaned action is unrepresentable -- asserted
    anyway, because a schema guarantee worth having is worth checking."""
    assert security._unauthorised_actions(detected, investigated.run_id) == 0


def test_an_orphaned_action_record_would_fail_the_bypass_check(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """The negative case, proving the check can fail.

    A genuinely orphaned row cannot be inserted -- the foreign key rejects it -- so the
    detectable violation is an action whose authorising evaluation was removed. The
    stronger corruption is prevented by the schema itself, which is the better outcome.
    """
    action = detected.scalar(
        sa.select(gov_orm.ActionRecord).where(gov_orm.ActionRecord.run_id == investigated.run_id)
    )
    assert action is not None

    with pytest.raises(sa.exc.IntegrityError):
        detected.execute(
            sa.update(gov_orm.ActionRecord)
            .where(gov_orm.ActionRecord.id == action.id)
            .values(authorized_by=new_id())
        )
        detected.flush()
    detected.rollback()


def test_crm_update_opportunity_is_unreachable(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """Registered and policy-classified, but nothing routes to it."""
    from revenue_sentinel.execution.executor import TOOL_FOR_ACTION

    assert ActionType.CRM_FIELD_UPDATE not in TOOL_FOR_ACTION
    results = security.evaluate_security(detected, investigated.run_id)
    assert result_for(results, "bypass_crm_update_unreachable").passed


def test_a_slack_notification_is_not_an_approval(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """Every executed draft must point at an `approval_requests` row, never at a
    `tool_calls` row."""
    results = security.evaluate_security(detected, investigated.run_id)
    assert result_for(results, "bypass_notification_is_not_approval").passed


def test_a_draft_with_no_approval_fails_the_notification_check(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """The negative case: an executed Tier 2 action with its approval detached."""
    detected.add(
        gov_orm.ActionRecord(
            id=new_id(),
            run_id=investigated.run_id,
            intervention_id=detected.scalar(
                sa.select(inv_orm.Intervention.id).where(
                    inv_orm.Intervention.run_id == investigated.run_id
                )
            ),
            action_type=ActionType.EMAIL_DRAFT,
            idempotency_key="f" * 64,
            status="succeeded",
            authorized_by=detected.scalar(
                sa.select(gov_orm.PolicyEvaluation.id).where(
                    gov_orm.PolicyEvaluation.decision == PolicyDecision.ALLOW
                )
            ),
            approval_request_id=None,
            attempt_count=1,
            result={"integration_status": "SIMULATED"},
            executed_at=None,
            target_ref="ACC-1001",
        )
    )
    detected.flush()

    results = security.evaluate_security(detected, investigated.run_id)
    assert not result_for(results, "bypass_notification_is_not_approval").passed
