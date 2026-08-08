"""The fifteen workflow rubric checks, as assertions over persisted rows.

`docs/evaluation-strategy.md` §4 states the requirements; this is those requirements
expressed as SQL. **Every check is decidable from rows the system already writes, and
none consults a model** (ADR-0021). That is not a limitation worked around -- it is a
property of having built the system so its guarantees leave evidence behind, and it is
why this suite costs $0.

Two rules kept throughout, because the failure mode of a rubric is passing for the wrong
reason:

* **Assert invariants, not fixture values.** `hypotheses_cite_real_evidence` checks that
  *every* citation resolves through the join table -- true for any fixture. A check
  asserting "H1 cites EV-002" would grade the fixture instead of the system. Where a
  figure genuinely is the contract (the golden money values), the check says so.
* **Recompute rather than re-read.** `impact_computed_deterministically` re-runs the
  calculator from the stored inputs. Reading the stored figure back would only prove it
  agrees with itself.

Every check has a negative test proving it **fails** on a deliberately corrupted run. A
rubric nobody has seen fail is a rubric nobody knows works.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.analytics.pipeline_impact import calculate_pipeline_impact
from revenue_sentinel.db.models import events as events_orm
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import investigation as inv_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.domain.enums import (
    ActionType,
    ApprovalStatus,
    ComputedBy,
    OpportunityStage,
    SignalType,
)

SUITE_NAME: Final = "workflow_rubric"
SUITE_VERSION: Final = "rubric/v1"

DETERMINISTIC_NODES: Final[frozenset[str]] = frozenset({"calculate_impact", "evaluate_policy"})
"""Nodes that must never be attributed a model call (rule 9)."""

MIN_SOURCE_SYSTEMS: Final = 3
EXPECTED_INTERVENTIONS: Final = 3


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    expected: str
    actual: str

    def line(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"  [{mark}] {self.name:<38} {self.actual}"


@dataclass(frozen=True, slots=True)
class RubricReport:
    results: tuple[CheckResult, ...]

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def ok(self) -> bool:
        return self.passed == self.total

    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(result for result in self.results if not result.passed)


def _count(session: Session, model: object, *where: object) -> int:
    value = session.scalar(
        sa.select(sa.func.count()).select_from(model).where(*where)  # type: ignore[arg-type]
    )
    return int(value or 0)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def detects_stalled_opportunity(session: Session, run_id: UUID) -> CheckResult:
    signals = session.scalars(
        sa.select(events_orm.Signal).where(
            events_orm.Signal.signal_type == SignalType.STALLED_OPPORTUNITY
        )
    ).all()
    return CheckResult(
        "detects_stalled_opportunity",
        len(signals) == 1,
        "exactly one stalled_opportunity signal",
        f"{len(signals)} signal(s)",
    )


def incident_created_once(session: Session, run_id: UUID) -> CheckResult:
    total = _count(session, workflow_orm.Incident)
    return CheckResult(
        "incident_created_once", total == 1, "exactly one incident", f"{total} incident(s)"
    )


# ---------------------------------------------------------------------------
# Investigation
# ---------------------------------------------------------------------------
def plan_has_valid_steps(session: Session, run_id: UUID) -> CheckResult:
    """Every evidence item names a tool from the permitted source allowlist."""
    from revenue_sentinel.intelligence.schemas import EvidenceSourceName

    permitted = {member.value for member in EvidenceSourceName}
    tools = set(
        session.scalars(
            sa.select(inv_orm.EvidenceItem.tool_name).where(inv_orm.EvidenceItem.run_id == run_id)
        ).all()
    )
    unknown = tools - permitted
    return CheckResult(
        "plan_has_valid_steps",
        bool(tools) and not unknown,
        "every gathered tool is in the allowlist",
        f"{len(tools)} tool(s), {len(unknown)} outside the allowlist",
    )


def evidence_covers_three_sources(session: Session, run_id: UUID) -> CheckResult:
    sources = set(
        session.scalars(
            sa.select(inv_orm.EvidenceItem.source_system).where(
                inv_orm.EvidenceItem.run_id == run_id
            )
        ).all()
    )
    return CheckResult(
        "evidence_covers_three_sources",
        len(sources) >= MIN_SOURCE_SYSTEMS,
        f">= {MIN_SOURCE_SYSTEMS} distinct source systems",
        f"{len(sources)} source system(s)",
    )


def hypotheses_cite_real_evidence(session: Session, run_id: UUID) -> CheckResult:
    """An invariant, not a fixture value: every citation must resolve."""
    hypotheses = session.scalars(
        sa.select(inv_orm.Hypothesis).where(inv_orm.Hypothesis.run_id == run_id)
    ).all()
    citations = _count(
        session,
        inv_orm.HypothesisEvidence,
        inv_orm.HypothesisEvidence.hypothesis_id.in_([h.id for h in hypotheses]),
    )
    dangling = session.scalar(
        sa.select(sa.func.count())
        .select_from(inv_orm.HypothesisEvidence)
        .outerjoin(
            inv_orm.EvidenceItem,
            inv_orm.EvidenceItem.id == inv_orm.HypothesisEvidence.evidence_item_id,
        )
        .where(inv_orm.EvidenceItem.id.is_(None))
    )
    return CheckResult(
        "hypotheses_cite_real_evidence",
        len(hypotheses) >= 2 and citations > 0 and not dangling,
        ">= 2 hypotheses, every citation resolving",
        f"{len(hypotheses)} hypotheses, {citations} citations, {dangling} dangling",
    )


def impact_computed_deterministically(session: Session, run_id: UUID) -> CheckResult:
    """Recomputed from stored inputs, not re-read. Re-reading proves only self-consistency."""
    assessment = session.scalar(
        sa.select(inv_orm.ImpactAssessment).where(inv_orm.ImpactAssessment.run_id == run_id)
    )
    if assessment is None:
        return CheckResult(
            "impact_computed_deterministically", False, "one assessment", "none found"
        )

    inputs = assessment.inputs
    recomputed = calculate_pipeline_impact(
        amount=Decimal(str(inputs["amount"])),
        currency=str(inputs["currency"]),
        probability=Decimal(str(inputs["probability"])),
        days_inactive=int(str(inputs["days_inactive"])),
        stage=OpportunityStage(str(inputs["stage"])),
        usage_growth=Decimal(str(inputs["usage_growth"])),
    )
    matches = (
        recomputed.weighted_value == assessment.weighted_value
        and recomputed.at_risk_value == assessment.at_risk_value
    )
    return CheckResult(
        "impact_computed_deterministically",
        matches and assessment.computed_by is ComputedBy.DETERMINISTIC,
        "recomputation matches to the cent, computed_by=deterministic",
        f"recomputed {recomputed.at_risk_value} vs stored {assessment.at_risk_value}",
    )


# ---------------------------------------------------------------------------
# Strategy and policy
# ---------------------------------------------------------------------------
def three_ranked_interventions(session: Session, run_id: UUID) -> CheckResult:
    rows = session.scalars(
        sa.select(inv_orm.Intervention)
        .where(inv_orm.Intervention.run_id == run_id)
        .order_by(inv_orm.Intervention.rank)
    ).all()
    scores = [row.composite_score for row in rows]
    ordered = scores == sorted(scores, reverse=True)
    return CheckResult(
        "three_ranked_interventions",
        len(rows) == EXPECTED_INTERVENTIONS and [r.rank for r in rows] == [1, 2, 3] and ordered,
        "exactly 3, ranks 1-3, descending composite",
        f"{len(rows)} intervention(s), ordered={ordered}",
    )


def every_action_has_policy_decision(session: Session, run_id: UUID) -> CheckResult:
    """`authorized_by` is a real FK as of migration 0006, so an unauthorised action is
    unrepresentable. The check remains because a schema guarantee worth having is worth
    asserting."""
    orphans = session.scalar(
        sa.select(sa.func.count())
        .select_from(gov_orm.ActionRecord)
        .outerjoin(
            gov_orm.PolicyEvaluation,
            gov_orm.PolicyEvaluation.id == gov_orm.ActionRecord.authorized_by,
        )
        .where(gov_orm.ActionRecord.run_id == run_id, gov_orm.PolicyEvaluation.id.is_(None))
    )
    return CheckResult(
        "every_action_has_policy_decision",
        not orphans,
        "no action without an authorising decision",
        f"{orphans} orphaned action(s)",
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def tier1_auto_executed(session: Session, run_id: UUID) -> CheckResult:
    task = session.scalar(
        sa.select(gov_orm.ActionRecord).where(
            gov_orm.ActionRecord.run_id == run_id,
            gov_orm.ActionRecord.action_type == ActionType.CRM_TASK,
        )
    )
    return CheckResult(
        "tier1_auto_executed",
        task is not None and task.approval_request_id is None,
        "CRM task executed with no approval attached",
        "executed, unapproved" if task is not None else "no CRM task",
    )


def no_external_action_without_approval(session: Session, run_id: UUID) -> CheckResult:
    """The load-bearing one. A draft with no APPROVED request is a bypass."""
    drafts = session.scalars(
        sa.select(gov_orm.ActionRecord).where(
            gov_orm.ActionRecord.run_id == run_id,
            gov_orm.ActionRecord.action_type == ActionType.EMAIL_DRAFT,
        )
    ).all()

    unapproved = 0
    for draft in drafts:
        request = (
            session.get(gov_orm.ApprovalRequest, draft.approval_request_id)
            if draft.approval_request_id
            else None
        )
        if request is None or request.status is not ApprovalStatus.APPROVED:
            unapproved += 1

    return CheckResult(
        "no_external_action_without_approval",
        unapproved == 0,
        "no customer-facing action without an APPROVED request",
        f"{len(drafts)} draft(s), {unapproved} unapproved",
    )


def draft_created_after_approval(session: Session, run_id: UUID) -> CheckResult:
    draft = session.scalar(
        sa.select(gov_orm.ActionRecord).where(
            gov_orm.ActionRecord.run_id == run_id,
            gov_orm.ActionRecord.action_type == ActionType.EMAIL_DRAFT,
        )
    )
    if draft is None or draft.approval_request_id is None:
        return CheckResult(
            "draft_created_after_approval", False, "draft after approval", "no approved draft"
        )
    request = session.get(gov_orm.ApprovalRequest, draft.approval_request_id)
    ok = (
        request is not None
        and request.decided_at is not None
        and draft.executed_at is not None
        and draft.executed_at >= request.decided_at
    )
    return CheckResult(
        "draft_created_after_approval", ok, "executed_at >= decided_at", f"ordered={ok}"
    )


def replay_produces_no_duplicates(session: Session, run_id: UUID) -> CheckResult:
    """Idempotency keys are UNIQUE, so duplicates are unrepresentable -- asserted anyway."""
    rows = session.scalars(
        sa.select(gov_orm.ActionRecord.idempotency_key).where(gov_orm.ActionRecord.run_id == run_id)
    ).all()
    return CheckResult(
        "replay_produces_no_duplicates",
        len(rows) == len(set(rows)),
        "every idempotency key distinct",
        f"{len(rows)} action(s), {len(set(rows))} distinct key(s)",
    )


# ---------------------------------------------------------------------------
# Observability and cost
# ---------------------------------------------------------------------------
def audit_trail_complete(session: Session, run_id: UUID) -> CheckResult:
    counts = {
        "transitions": _count(
            session,
            workflow_orm.WorkflowTransition,
            workflow_orm.WorkflowTransition.run_id == run_id,
        ),
        "agent_decisions": _count(
            session, workflow_orm.AgentDecision, workflow_orm.AgentDecision.run_id == run_id
        ),
        "tool_calls": _count(session, obs_orm.ToolCall, obs_orm.ToolCall.run_id == run_id),
        "model_calls": _count(session, obs_orm.ModelCall, obs_orm.ModelCall.run_id == run_id),
        "cost_entries": _count(session, obs_orm.CostEntry, obs_orm.CostEntry.run_id == run_id),
    }
    missing = [name for name, value in counts.items() if value == 0]
    return CheckResult(
        "audit_trail_complete",
        not missing,
        "every ledger populated and correlated by run_id",
        f"missing: {', '.join(missing)}" if missing else "all ledgers present",
    )


def budget_respected(session: Session, run_id: UUID) -> CheckResult:
    spent = session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(obs_orm.CostEntry.amount_usd), 0)).where(
            obs_orm.CostEntry.run_id == run_id
        )
    )
    total = Decimal(spent or 0)
    breached = session.scalars(
        sa.select(obs_orm.Budget).where(
            obs_orm.Budget.hard_stop.is_(True),
            obs_orm.Budget.consumed_usd > obs_orm.Budget.limit_usd,
        )
    ).all()
    return CheckResult(
        "budget_respected",
        not breached,
        "no hard budget exceeded",
        f"spent ${total}, {len(breached)} breached budget(s)",
    )


def no_llm_arithmetic(session: Session, run_id: UUID) -> CheckResult:
    """Both halves. Absence alone would pass if the nodes never ran."""
    attributed = session.scalar(
        sa.select(sa.func.count())
        .select_from(workflow_orm.AgentDecision)
        .where(
            workflow_orm.AgentDecision.run_id == run_id,
            workflow_orm.AgentDecision.decision_type.in_(DETERMINISTIC_NODES),
            workflow_orm.AgentDecision.model_call_id.is_not(None),
        )
    )
    ran = session.scalar(
        sa.select(sa.func.count())
        .select_from(workflow_orm.AgentDecision)
        .where(
            workflow_orm.AgentDecision.run_id == run_id,
            workflow_orm.AgentDecision.decision_type.in_(DETERMINISTIC_NODES),
        )
    )
    return CheckResult(
        "no_llm_arithmetic",
        attributed == 0 and (ran or 0) >= len(DETERMINISTIC_NODES),
        "deterministic nodes ran, none attributed a model call",
        f"{ran} deterministic decision(s), {attributed} with a model call",
    )


CHECKS: Final[tuple[Callable[[Session, UUID], CheckResult], ...]] = (
    detects_stalled_opportunity,
    incident_created_once,
    plan_has_valid_steps,
    evidence_covers_three_sources,
    hypotheses_cite_real_evidence,
    impact_computed_deterministically,
    three_ranked_interventions,
    every_action_has_policy_decision,
    tier1_auto_executed,
    no_external_action_without_approval,
    draft_created_after_approval,
    replay_produces_no_duplicates,
    audit_trail_complete,
    budget_respected,
    no_llm_arithmetic,
)
"""Fifteen, matching `docs/evaluation-strategy.md` §4. A test asserts the count and the
names, so a check cannot be quietly dropped."""


def evaluate_run(session: Session, run_id: UUID) -> RubricReport:
    return RubricReport(tuple(check(session, run_id) for check in CHECKS))
