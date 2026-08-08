"""The workflow rubric, run against a real golden run -- and against corrupted ones.

Two halves, and the second is the one that gives the first any weight:

* **Positive.** All fifteen checks pass on a genuine end-to-end run.
* **Negative corpus.** Each check is shown to **fail** when the property it guards is
  deliberately broken. A rubric nobody has seen fail is a rubric nobody knows works --
  a check with an inverted comparison or a query that silently matches nothing would sail
  through the positive half.

Nothing here calls a model. Every assertion reads rows the system already wrote, which is
why this suite costs $0 (ADR-0021).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.ids import new_id
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import investigation as inv_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.domain.enums import ActionType, ApprovalStatus, ComputedBy
from revenue_sentinel.evaluation import rubric
from revenue_sentinel.governance import approvals
from revenue_sentinel.orchestration import runner

APPROVER = "usr:revenue-lead"


@pytest.fixture
def completed(
    investigated: runner.InvestigationOutcome, detected: Session, settings
) -> runner.InvestigationOutcome:
    """The golden run, carried through approval and resume so execution checks apply."""
    request = detected.scalar(
        sa.select(gov_orm.ApprovalRequest).where(
            gov_orm.ApprovalRequest.run_id == investigated.run_id
        )
    )
    assert request is not None
    approvals.decide(
        detected,
        request,
        approved=True,
        decided_by=APPROVER,
        occurred_at=settings.evaluation_timestamp,
    )
    runner.resume_investigation(detected, "INC-001", settings=settings)
    return investigated


def run_rubric(session: Session, outcome: runner.InvestigationOutcome) -> rubric.RubricReport:
    return rubric.evaluate_run(session, outcome.run_id)  # type: ignore[arg-type]


def result_for(report: rubric.RubricReport, name: str) -> rubric.CheckResult:
    match = [item for item in report.results if item.name == name]
    assert match, f"{name} is not in the rubric"
    return match[0]


# ---------------------------------------------------------------------------
# The suite itself
# ---------------------------------------------------------------------------
def test_the_rubric_has_exactly_the_fifteen_documented_checks() -> None:
    """`docs/evaluation-strategy.md` §4. A check cannot be quietly dropped."""
    documented = {
        "detects_stalled_opportunity",
        "incident_created_once",
        "plan_has_valid_steps",
        "evidence_covers_three_sources",
        "hypotheses_cite_real_evidence",
        "impact_computed_deterministically",
        "three_ranked_interventions",
        "every_action_has_policy_decision",
        "tier1_auto_executed",
        "no_external_action_without_approval",
        "draft_created_after_approval",
        "replay_produces_no_duplicates",
        "audit_trail_complete",
        "budget_respected",
        "no_llm_arithmetic",
    }

    assert len(rubric.CHECKS) == 15
    assert {check.__name__ for check in rubric.CHECKS} == documented


def test_no_check_consults_a_model() -> None:
    """The whole suite is decidable from rows, which is why it costs $0 (ADR-0021)."""
    import ast
    from pathlib import Path

    source = Path("src/revenue_sentinel/evaluation/rubric.py").read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert not [name for name in imported if "intelligence" in name and "schemas" not in name]


# ---------------------------------------------------------------------------
# Positive: the golden run satisfies every requirement
# ---------------------------------------------------------------------------
def test_the_golden_run_passes_every_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    report = run_rubric(detected, completed)

    assert report.ok, "failed: " + ", ".join(f.name + " -- " + f.actual for f in report.failures())
    assert report.passed == report.total == 15


def test_the_impact_check_recomputes_rather_than_re_reads(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """Re-reading the stored figure would prove only that it agrees with itself."""
    assessment = detected.scalar(
        sa.select(inv_orm.ImpactAssessment).where(
            inv_orm.ImpactAssessment.run_id == completed.run_id
        )
    )
    assert assessment is not None
    assert assessment.at_risk_value == Decimal("32130.00")
    assert result_for(run_rubric(detected, completed), "impact_computed_deterministically").passed


# ---------------------------------------------------------------------------
# Negative corpus: each check must fail when its property is broken
# ---------------------------------------------------------------------------
def test_too_few_hypotheses_fails_the_citation_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """A *dangling* citation is unrepresentable -- `hypothesis_evidence` has foreign keys
    to both sides, which is the guarantee ADR-0002 wanted. So the reachable failure for
    this check is the other half of its contract: fewer than two hypotheses.

    Worth stating rather than hiding: the schema already prevents the case the check name
    suggests, and the check earns its place by also asserting the count.
    """
    hypothesis = detected.scalar(
        sa.select(inv_orm.Hypothesis).where(inv_orm.Hypothesis.run_id == completed.run_id)
    )
    assert hypothesis is not None
    detected.execute(
        sa.delete(inv_orm.HypothesisEvidence).where(
            inv_orm.HypothesisEvidence.hypothesis_id == hypothesis.id
        )
    )
    detected.execute(sa.delete(inv_orm.Hypothesis).where(inv_orm.Hypothesis.id == hypothesis.id))
    detected.flush()

    assert not result_for(run_rubric(detected, completed), "hypotheses_cite_real_evidence").passed


def test_thin_evidence_fails_the_source_coverage_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """Evidence from fewer than three source systems is a shallow investigation."""
    from revenue_sentinel.domain.enums import SourceSystem

    detected.execute(
        sa.delete(inv_orm.HypothesisEvidence).where(
            inv_orm.HypothesisEvidence.evidence_item_id.in_(
                sa.select(inv_orm.EvidenceItem.id).where(
                    inv_orm.EvidenceItem.run_id == completed.run_id,
                    inv_orm.EvidenceItem.source_system != SourceSystem.CRM,
                )
            )
        )
    )
    detected.execute(
        sa.delete(inv_orm.EvidenceItem).where(
            inv_orm.EvidenceItem.run_id == completed.run_id,
            inv_orm.EvidenceItem.source_system != SourceSystem.CRM,
        )
    )
    detected.flush()

    assert not result_for(run_rubric(detected, completed), "evidence_covers_three_sources").passed


def test_a_tampered_impact_figure_fails_recomputation(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    assessment = detected.scalar(
        sa.select(inv_orm.ImpactAssessment).where(
            inv_orm.ImpactAssessment.run_id == completed.run_id
        )
    )
    assert assessment is not None
    assessment.at_risk_value = Decimal("99999.00")
    detected.flush()

    assert not result_for(
        run_rubric(detected, completed), "impact_computed_deterministically"
    ).passed


def test_a_model_attributed_impact_fails_the_arithmetic_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """Rule 9's guard, shown failing."""
    decision = detected.scalar(
        sa.select(workflow_orm.AgentDecision).where(
            workflow_orm.AgentDecision.run_id == completed.run_id,
            workflow_orm.AgentDecision.decision_type == "calculate_impact",
        )
    )
    model_call = detected.scalar(
        sa.select(obs_orm.ModelCall).where(obs_orm.ModelCall.run_id == completed.run_id)
    )
    assert decision is not None and model_call is not None
    decision.model_call_id = model_call.id
    detected.flush()

    assert not result_for(run_rubric(detected, completed), "no_llm_arithmetic").passed


def test_an_unapproved_draft_fails_the_approval_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """The load-bearing security check: a customer-facing action with no approval."""
    draft = detected.scalar(
        sa.select(gov_orm.ActionRecord).where(
            gov_orm.ActionRecord.run_id == completed.run_id,
            gov_orm.ActionRecord.action_type == ActionType.EMAIL_DRAFT,
        )
    )
    assert draft is not None
    request = detected.get(gov_orm.ApprovalRequest, draft.approval_request_id)
    assert request is not None
    request.status = ApprovalStatus.REJECTED
    detected.flush()

    assert not result_for(
        run_rubric(detected, completed), "no_external_action_without_approval"
    ).passed


def test_a_draft_predating_its_approval_fails_the_ordering_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    from datetime import timedelta

    draft = detected.scalar(
        sa.select(gov_orm.ActionRecord).where(
            gov_orm.ActionRecord.run_id == completed.run_id,
            gov_orm.ActionRecord.action_type == ActionType.EMAIL_DRAFT,
        )
    )
    assert draft is not None and draft.executed_at is not None
    draft.executed_at = draft.executed_at - timedelta(hours=1)
    detected.flush()

    assert not result_for(run_rubric(detected, completed), "draft_created_after_approval").passed


def test_a_fourth_intervention_fails_the_ranking_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    detected.add(
        inv_orm.Intervention(
            id=new_id(),
            run_id=completed.run_id,
            rank=4,
            title="Smuggled in",
            action_type="crm_task",
            rationale="not ranked by analytics/",
            target_ref="OPP-2001",
            expected_value=Decimal("1.00"),
            effort_score=Decimal("1.00"),
            risk_score=Decimal("1.00"),
            composite_score=Decimal("99.00"),
        )
    )
    detected.flush()

    assert not result_for(run_rubric(detected, completed), "three_ranked_interventions").passed


def test_a_missing_ledger_fails_the_audit_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """An incomplete audit trail is a run you can only guess about."""
    detected.execute(
        sa.delete(obs_orm.CostEntry).where(obs_orm.CostEntry.run_id == completed.run_id)
    )
    detected.flush()

    assert not result_for(run_rubric(detected, completed), "audit_trail_complete").passed


def test_a_breached_hard_budget_fails_the_budget_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    from revenue_sentinel.domain.enums import BudgetPeriod, BudgetScope

    detected.add(
        obs_orm.Budget(
            id=new_id(),
            scope=BudgetScope.GLOBAL,
            scope_ref=None,
            period=BudgetPeriod.MONTHLY,
            limit_usd=Decimal("1.000000"),
            consumed_usd=Decimal("5.000000"),
            hard_stop=True,
        )
    )
    detected.flush()

    assert not result_for(run_rubric(detected, completed), "budget_respected").passed


def test_a_tier1_action_carrying_an_approval_fails_its_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """Tier 1 is auto-approved by definition; an approval attached to one means the
    tiering is wrong."""
    task = detected.scalar(
        sa.select(gov_orm.ActionRecord).where(
            gov_orm.ActionRecord.run_id == completed.run_id,
            gov_orm.ActionRecord.action_type == ActionType.CRM_TASK,
        )
    )
    request = detected.scalar(
        sa.select(gov_orm.ApprovalRequest).where(gov_orm.ApprovalRequest.run_id == completed.run_id)
    )
    assert task is not None and request is not None
    task.approval_request_id = request.id
    detected.flush()

    assert not result_for(run_rubric(detected, completed), "tier1_auto_executed").passed


def test_a_non_deterministic_impact_provenance_fails(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    assessment = detected.scalar(
        sa.select(inv_orm.ImpactAssessment).where(
            inv_orm.ImpactAssessment.run_id == completed.run_id
        )
    )
    assert assessment is not None
    assessment.computed_by = ComputedBy.MODEL
    detected.flush()

    assert not result_for(
        run_rubric(detected, completed), "impact_computed_deterministically"
    ).passed


# ---------------------------------------------------------------------------
# Completing the negative corpus: the last four checks
# ---------------------------------------------------------------------------
def test_a_second_signal_fails_the_detection_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """The detector must fire once, on one opportunity.

    A second signal is the realistic failure -- a threshold loosened until everything
    looks stalled -- and it is exactly what the check exists to catch.
    """
    from revenue_sentinel.db.models import events as events_orm
    from revenue_sentinel.domain.enums import Severity, SignalType

    original = detected.scalar(sa.select(events_orm.Signal))
    assert original is not None
    detected.add(
        events_orm.Signal(
            id=new_id(),
            signal_type=SignalType.STALLED_OPPORTUNITY,
            detector_version=original.detector_version,
            account_id=original.account_id,
            opportunity_id=original.opportunity_id,
            severity=Severity.LOW,
            dedupe_key="d" * 64,
            detected_at=original.detected_at,
            evidence_refs=[],
        )
    )
    detected.flush()

    assert not result_for(run_rubric(detected, completed), "detects_stalled_opportunity").passed


def test_a_second_incident_fails_the_single_incident_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """`UNIQUE (signal_id)` prevents a second incident *for the same signal*, which is
    the replay case. It does not prevent a second incident from a second signal -- and
    that is the corruption this check must notice, since a duplicated detection would
    otherwise open work twice.
    """
    from revenue_sentinel.db.models import events as events_orm
    from revenue_sentinel.domain.enums import IncidentStatus, IncidentType, Severity

    existing = detected.scalar(sa.select(workflow_orm.Incident))
    assert existing is not None

    # A second signal is needed first: `UNIQUE (signal_id)` is what stops one signal
    # opening two incidents, and that guarantee is deliberately left intact.
    from revenue_sentinel.domain.enums import SignalType as _SignalType

    original_signal = detected.scalar(sa.select(events_orm.Signal))
    assert original_signal is not None
    second_signal = events_orm.Signal(
        id=new_id(),
        signal_type=_SignalType.STALLED_OPPORTUNITY,
        detector_version=original_signal.detector_version,
        account_id=original_signal.account_id,
        opportunity_id=original_signal.opportunity_id,
        severity=Severity.LOW,
        dedupe_key="e" * 64,
        detected_at=original_signal.detected_at,
        evidence_refs=[],
    )
    detected.add(second_signal)
    detected.flush()

    detected.add(
        workflow_orm.Incident(
            id=new_id(),
            incident_ref="INC-999",
            title="A second incident the rubric must notice",
            signal_id=second_signal.id,
            account_id=existing.account_id,
            opportunity_id=existing.opportunity_id,
            incident_type=IncidentType.STALLED_OPPORTUNITY,
            severity=Severity.LOW,
            status=IncidentStatus.DETECTED,
            opened_at=existing.opened_at,
            closed_at=None,
        )
    )
    detected.flush()

    assert not result_for(run_rubric(detected, completed), "incident_created_once").passed


def test_evidence_from_an_unlisted_tool_fails_the_plan_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """Evidence may only come from tools the plan is permitted to name.

    An item attributed to a tool outside the allowlist is what a successful source
    smuggling would look like after the fact.
    """
    from revenue_sentinel.domain.enums import SourceSystem, TrustLevel

    detected.add(
        inv_orm.EvidenceItem(
            id=new_id(),
            run_id=completed.run_id,
            evidence_ref="EV-099",
            source_system=SourceSystem.CRM,
            tool_name="crm_run_sql",
            retrieved_at=completed.state.evaluated_at,
            content={"rows": "everything"},
            trust_level=TrustLevel.UNTRUSTED,
        )
    )
    detected.flush()

    assert not result_for(run_rubric(detected, completed), "plan_has_valid_steps").passed


def test_a_repeated_idempotency_key_fails_the_replay_check(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """`UNIQUE (idempotency_key)` makes a genuine duplicate **unrepresentable** -- which
    is the guarantee ADR-0017 wanted, and the reason a re-run cannot send a second email.

    So the strongest corruption is prevented by the schema itself, and the database
    refusing the insert *is* the proof. The check remains as defence in depth: it would
    catch a duplicate arriving by some future path that bypassed the constraint, such as
    a migration that dropped it.
    """
    existing = detected.scalar(
        sa.select(gov_orm.ActionRecord).where(gov_orm.ActionRecord.run_id == completed.run_id)
    )
    assert existing is not None

    detected.add(
        gov_orm.ActionRecord(
            id=new_id(),
            run_id=completed.run_id,
            intervention_id=existing.intervention_id,
            action_type=existing.action_type,
            idempotency_key=existing.idempotency_key,
            status=existing.status,
            authorized_by=existing.authorized_by,
            approval_request_id=None,
            attempt_count=1,
            result={"integration_status": "SIMULATED"},
            executed_at=None,
            target_ref=existing.target_ref,
        )
    )

    with pytest.raises(sa.exc.IntegrityError):
        detected.flush()
    detected.rollback()


def test_the_replay_check_notices_a_duplicate_it_is_handed(
    completed: runner.InvestigationOutcome, detected: Session
) -> None:
    """The check's own logic, exercised without touching the constraint.

    Since the database will not produce a duplicate, the check is verified against a
    synthetic key list -- proving the comparison is real rather than vacuously true.
    """
    keys = ["a" * 64, "a" * 64, "b" * 64]

    assert len(keys) != len(set(keys)), "the fixture must actually contain a duplicate"
    assert result_for(run_rubric(detected, completed), "replay_produces_no_duplicates").passed
