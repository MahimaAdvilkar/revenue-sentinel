"""Evaluation history is append-only, and one row per check per attempt.

The property that matters: a later evaluation can never erase the evidence that an
earlier one failed. That is the whole reason to keep evaluation history rather than a
current-status flag.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.db.models import evaluation as eval_orm
from revenue_sentinel.domain.enums import EvaluationOutcome
from revenue_sentinel.evaluation.service import EVALUATOR_VERSION, evaluate, render
from revenue_sentinel.orchestration import runner


def results_for(session: Session, evaluation_run_id: object) -> list[eval_orm.EvaluationResult]:
    return list(
        session.scalars(
            sa.select(eval_orm.EvaluationResult).where(
                eval_orm.EvaluationResult.evaluation_run_id == evaluation_run_id
            )
        ).all()
    )


def test_one_invocation_persists_one_run_and_one_row_per_check(
    investigated: runner.InvestigationOutcome, detected: Session, settings
) -> None:
    evaluation = evaluate(
        detected, run_id=investigated.run_id, occurred_at=settings.evaluation_timestamp
    )
    rows = results_for(detected, evaluation.evaluation_run_id)

    assert len(rows) == len(evaluation.all_checks)
    assert {row.check_name for row in rows} == {c.name for c in evaluation.all_checks}
    assert len({row.check_name for row in rows}) == len(rows), "a check appeared twice"


def test_two_invocations_append_rather_than_overwrite(
    investigated: runner.InvestigationOutcome, detected: Session, settings
) -> None:
    """The audit property. A second attempt must not touch the first."""
    first = evaluate(
        detected, run_id=investigated.run_id, occurred_at=settings.evaluation_timestamp
    )
    before = {
        (r.check_name, r.outcome, r.actual) for r in results_for(detected, first.evaluation_run_id)
    }

    second = evaluate(
        detected, run_id=investigated.run_id, occurred_at=settings.evaluation_timestamp
    )

    assert second.evaluation_run_id != first.evaluation_run_id
    after = {
        (r.check_name, r.outcome, r.actual) for r in results_for(detected, first.evaluation_run_id)
    }
    assert after == before, "the earlier attempt was mutated"

    runs = detected.scalars(sa.select(eval_orm.EvaluationRun)).all()
    assert len(runs) >= 2


def test_a_failing_attempt_stays_on_the_record(
    investigated: runner.InvestigationOutcome, detected: Session, settings
) -> None:
    """Corrupt, evaluate, repair, evaluate. The failure must survive the repair."""
    from decimal import Decimal

    from revenue_sentinel.db.models import investigation as inv_orm

    assessment = detected.scalar(
        sa.select(inv_orm.ImpactAssessment).where(
            inv_orm.ImpactAssessment.run_id == investigated.run_id
        )
    )
    assert assessment is not None
    original = assessment.at_risk_value

    assessment.at_risk_value = Decimal("1.00")
    detected.flush()
    failed = evaluate(
        detected, run_id=investigated.run_id, occurred_at=settings.evaluation_timestamp
    )

    assessment.at_risk_value = original
    detected.flush()
    repaired = evaluate(
        detected, run_id=investigated.run_id, occurred_at=settings.evaluation_timestamp
    )

    failed_rows = {r.check_name: r.outcome for r in results_for(detected, failed.evaluation_run_id)}
    repaired_rows = {
        r.check_name: r.outcome for r in results_for(detected, repaired.evaluation_run_id)
    }

    assert failed_rows["impact_computed_deterministically"] is EvaluationOutcome.FAILED
    assert repaired_rows["impact_computed_deterministically"] is EvaluationOutcome.PASSED


def test_the_evaluator_version_is_recorded(
    investigated: runner.InvestigationOutcome, detected: Session, settings
) -> None:
    """`suite_version` is the schema's intended field -- no migration was needed."""
    evaluation = evaluate(
        detected, run_id=investigated.run_id, occurred_at=settings.evaluation_timestamp
    )
    run = detected.get(eval_orm.EvaluationRun, evaluation.evaluation_run_id)

    assert run is not None
    assert run.suite_version == EVALUATOR_VERSION
    assert run.total == len(evaluation.all_checks)
    assert run.passed == sum(1 for c in evaluation.all_checks if c.passed)


def test_a_failure_persists_an_explanation(
    investigated: runner.InvestigationOutcome, detected: Session, settings
) -> None:
    """A failure that does not explain itself makes the next reader re-derive the check."""
    from revenue_sentinel.db.models import observability as obs_orm

    detected.execute(
        sa.delete(obs_orm.CostEntry).where(obs_orm.CostEntry.run_id == investigated.run_id)
    )
    detected.flush()

    evaluation = evaluate(
        detected, run_id=investigated.run_id, occurred_at=settings.evaluation_timestamp
    )
    row = next(
        r
        for r in results_for(detected, evaluation.evaluation_run_id)
        if r.check_name == "audit_trail_complete"
    )

    assert row.outcome is EvaluationOutcome.FAILED
    assert row.detail is not None
    assert EVALUATOR_VERSION in row.detail
    assert row.expected and row.actual


def test_the_report_shows_the_same_checks_that_were_persisted(
    investigated: runner.InvestigationOutcome, detected: Session, settings
) -> None:
    """One implementation. A separate rendering path would eventually disagree with the
    record, and the disagreement would surface while explaining a historical result."""
    evaluation = evaluate(
        detected, run_id=investigated.run_id, occurred_at=settings.evaluation_timestamp
    )
    report = "\n".join(render(evaluation, incident_ref="INC-001"))

    for row in results_for(detected, evaluation.evaluation_run_id):
        assert row.check_name in report

    assert "LLM judge:        NOT USED" in report
    assert "evaluation cost:  $0.000000" in report


def test_evaluation_consults_no_model(
    investigated: runner.InvestigationOutcome, detected: Session, settings
) -> None:
    """The suite costs $0 because nothing in it can spend."""
    import sys

    sys.modules.pop("anthropic", None)
    evaluate(detected, run_id=investigated.run_id, occurred_at=settings.evaluation_timestamp)

    assert "anthropic" not in sys.modules
