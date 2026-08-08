"""One evaluation execution: evaluate, persist, render -- in that order, once.

**There is deliberately one implementation.** The checks `make eval` prints are the same
objects written to `evaluation_results`; a separate rendering path would eventually
disagree with the persisted record, and the disagreement would be discovered by someone
trying to explain a historical result.

**Append-only.** Every invocation creates a new `evaluation_runs` row. Nothing is ever
overwritten, so a later run cannot quietly erase the evidence that an earlier one failed
-- which is the whole point of keeping evaluation history at all. The existing
`UNIQUE (evaluation_run_id, check_name)` then guarantees exactly one result per check
*within* an attempt, without constraining how many attempts there are.

`suite_version` carries the evaluator version. It is the schema's intended field for
exactly this, so no migration was needed -- a result can be read against the evaluator
that produced it, the same way `pricing_version` works for costs.

**No model is consulted.** Not by the checks, not by the reporter (ADR-0021).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from revenue_sentinel.core.ids import new_id
from revenue_sentinel.db.models import evaluation as eval_orm
from revenue_sentinel.domain.enums import EvaluationOutcome
from revenue_sentinel.evaluation import security
from revenue_sentinel.evaluation.rubric import CheckResult, evaluate_run

EVALUATOR_VERSION: Final = "evaluator/v1"
SUITE_NAME: Final = "workflow_and_security"

WORKFLOW_SECTION: Final = "WORKFLOW RUBRIC"
INJECTION_SECTION: Final = "PROMPT-INJECTION SECURITY"
INVARIANT_SECTION: Final = "SECURITY INVARIANTS"
BYPASS_SECTION: Final = "POLICY BYPASS"

EVALUATION_COST: Final = Decimal("0.000000")
"""Not a rounding. No check consults a model, so evaluating costs nothing at all."""


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Everything one invocation produced."""

    evaluation_run_id: UUID
    workflow_run_id: UUID
    workflow: tuple[CheckResult, ...]
    injection: tuple[CheckResult, ...]
    """Exactly the six named cases from `docs/security-model.md` §2."""

    invariants: tuple[CheckResult, ...]
    """Cross-cutting security properties that hold regardless of any attempted attack.
    Reported separately so the corpus count stays honest at six."""

    bypass: tuple[CheckResult, ...]

    @property
    def all_checks(self) -> tuple[CheckResult, ...]:
        return self.workflow + self.injection + self.invariants + self.bypass

    @property
    def ok(self) -> bool:
        return all(check.passed for check in self.all_checks)

    def section(self, results: tuple[CheckResult, ...]) -> str:
        return f"{sum(1 for r in results if r.passed)}/{len(results)}"


def evaluate(session: Session, *, run_id: UUID, occurred_at: datetime) -> Evaluation:
    """Run every check, then persist the results. Rendering is a separate concern."""
    workflow = evaluate_run(session, run_id).results
    everything = security.evaluate_security(session, run_id)
    injection = tuple(check for check in everything if check.name.startswith("injection_"))
    invariants = tuple(check for check in everything if check.name.startswith("invariant_"))
    bypass = tuple(check for check in everything if check.name.startswith("bypass_"))

    evaluation_run = _persist(
        session,
        run_id=run_id,
        results=workflow + injection + invariants + bypass,
        occurred_at=occurred_at,
    )

    return Evaluation(
        evaluation_run_id=evaluation_run.id,
        workflow_run_id=run_id,
        workflow=workflow,
        injection=injection,
        invariants=invariants,
        bypass=bypass,
    )


def _persist(
    session: Session,
    *,
    run_id: UUID,
    results: tuple[CheckResult, ...],
    occurred_at: datetime,
) -> eval_orm.EvaluationRun:
    """A new attempt every time. Prior attempts are never touched."""
    evaluation_run = eval_orm.EvaluationRun(
        id=new_id(),
        suite_name=SUITE_NAME,
        suite_version=EVALUATOR_VERSION,
        started_at=occurred_at,
        ended_at=occurred_at,
        passed=sum(1 for result in results if result.passed),
        total=len(results),
    )
    session.add(evaluation_run)
    session.flush()

    for result in results:
        session.add(
            eval_orm.EvaluationResult(
                id=new_id(),
                evaluation_run_id=evaluation_run.id,
                workflow_run_id=run_id,
                check_name=result.name,
                outcome=EvaluationOutcome.PASSED if result.passed else EvaluationOutcome.FAILED,
                expected=result.expected,
                actual=result.actual,
                detail=None if result.passed else f"{EVALUATOR_VERSION}: {result.actual}",
            )
        )
    session.flush()
    return evaluation_run


def render(evaluation: Evaluation, *, incident_ref: str) -> list[str]:
    """The report. Deterministic, and it consults nothing."""
    lines = [f"EVALUATION -- {incident_ref}", ""]

    for title, results in (
        (WORKFLOW_SECTION, evaluation.workflow),
        (INJECTION_SECTION, evaluation.injection),
        (INVARIANT_SECTION, evaluation.invariants),
        (BYPASS_SECTION, evaluation.bypass),
    ):
        lines.append(title)
        for result in results:
            mark = "PASS" if result.passed else "FAIL"
            lines.append(f"  {mark}  {result.name}")
            if not result.passed:
                # A failure that does not explain itself makes the next person re-derive
                # the check from scratch.
                lines.append(f"        expected: {result.expected}")
                lines.append(f"        actual:   {result.actual}")
        lines.append("")

    lines += [
        "SUMMARY",
        f"  workflow rubric:  {evaluation.section(evaluation.workflow)}",
        f"  injection corpus: {evaluation.section(evaluation.injection)}",
        f"  security invariants: {evaluation.section(evaluation.invariants)}",
        f"  policy bypass:    {evaluation.section(evaluation.bypass)}",
        f"  overall:          {'PASS' if evaluation.ok else 'FAIL'}",
        "  LLM judge:        NOT USED",
        f"  evaluation cost:  ${EVALUATION_COST}",
        f"  evaluator:        {EVALUATOR_VERSION}",
        f"  evaluation run:   {evaluation.evaluation_run_id}",
    ]
    return lines
