"""Writing what the graph produced.

All of it lives here rather than in node bodies (ADR-0002 rule 1). A node returns
state; this turns state into rows.

Two things are worth pointing at:

**`model_calls` never implies a call that did not happen.** In fixture mode a row is
still written -- so `agent_decisions.model_call_id` links an LLM-backed agent to its
call site -- but it carries `is_replay = true`, zero tokens, and
`stop_reason = "fixture_replay"`. Zero, because zero were consumed. Nothing here
estimates or back-fills usage. See ADR-0013.

**`calculate_impact` writes `model_call_id = NULL`.** That is not an omission, it is
the proof: `SELECT ... WHERE model_call_id IS NULL` is how Session 8 shows the
arithmetic never touched a model.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from revenue_sentinel.agents.policy_agent import POLICY_ACTOR
from revenue_sentinel.analytics.pipeline_impact import PipelineImpact
from revenue_sentinel.core.ids import hypothesis_ref, new_id
from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import investigation as orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import ComputedBy, PolicyDecision, TrustLevel
from revenue_sentinel.governance.approvals import create_approval_request
from revenue_sentinel.intelligence.ports import LLMResponse
from revenue_sentinel.orchestration.state import WorkflowState

TRACE_ID_LENGTH = 32
SPAN_ID_LENGTH = 16


def _hex_id(*parts: str, length: int) -> str:
    """A deterministic hex identifier, so a replayed run traces identically."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:length]


def digest_of(payload: JSONObject) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PersistedInvestigation:
    """Row counts, for the CLI to print and tests to assert on."""

    evidence_items: int
    hypotheses: int
    citations: int
    impact_assessment_id: UUID
    interventions: int = 0
    policy_evaluations: int = 0
    approval_requests: int = 0


def record_model_call(
    session: Session,
    *,
    run_id: UUID,
    node_name: str,
    response: LLMResponse[BaseModel],
) -> obs_orm.ModelCall:
    """Write one `model_calls` row.

    In fixture mode the token counts are zero and `is_replay` is true. The row records
    that an LLM call *site* was exercised and how; it does not claim an API call
    occurred.
    """
    model_call = obs_orm.ModelCall(
        id=new_id(),
        run_id=run_id,
        node_name=node_name,
        model_id=response.model_id,
        effort=response.effort,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cache_read_tokens=0,
        cache_write_tokens=0,
        latency_ms=response.latency_ms,
        stop_reason=response.stop_reason,
        is_replay=response.is_replay,
        trace_id=_hex_id(str(run_id), length=TRACE_ID_LENGTH),
        span_id=_hex_id(str(run_id), node_name, length=SPAN_ID_LENGTH),
    )
    session.add(model_call)
    session.flush()
    return model_call


def record_agent_decision(
    session: Session,
    *,
    run_id: UUID,
    agent_name: str,
    decision_type: str,
    rationale: str,
    inputs: JSONObject,
    output: JSONObject,
    model_call_id: UUID | None,
) -> None:
    """Write one `agent_decisions` row.

    `model_call_id` is `None` for every deterministic agent, which is the whole point
    of the column being nullable.
    """
    from revenue_sentinel.db.models import workflow as workflow_orm

    decision = workflow_orm.AgentDecision(
        id=new_id(),
        run_id=run_id,
        agent_name=agent_name,
        decision_type=decision_type,
        rationale=rationale,
        inputs_digest=digest_of(inputs),
        output=output,
        model_call_id=model_call_id,
    )
    session.add(decision)
    session.flush()


def persist_investigation(
    session: Session, state: WorkflowState, *, occurred_at: datetime
) -> PersistedInvestigation:
    """Write evidence, hypotheses, their citations, and the impact assessment.

    Called only after citation validation has passed, so a fabricated citation never
    reaches this function -- and `hypothesis_evidence`'s foreign keys mean it could
    not be written even if it did.
    """
    if state.hypotheses is None or state.impact is None:
        raise ValueError("cannot persist an incomplete investigation")

    evidence_ids: dict[str, UUID] = {}
    for item in state.evidence:
        row = orm.EvidenceItem(
            id=new_id(),
            run_id=state.run_id,
            evidence_ref=item.evidence_ref,
            source_system=item.record.source_system,
            tool_name=item.record.tool_name,
            retrieved_at=occurred_at,
            content=item.record.content,
            trust_level=TrustLevel.UNTRUSTED,
        )
        session.add(row)
        evidence_ids[item.evidence_ref] = row.id
    session.flush()

    citations = 0
    for draft in sorted(state.hypotheses.hypotheses, key=lambda item: item.rank):
        hypothesis = orm.Hypothesis(
            id=new_id(),
            run_id=state.run_id,
            hypothesis_ref=hypothesis_ref(draft.rank),
            statement=draft.statement,
            confidence=draft.confidence,
            rank=draft.rank,
        )
        session.add(hypothesis)
        session.flush()

        for ref in sorted(set(draft.cites)):
            session.add(
                orm.HypothesisEvidence(
                    id=new_id(),
                    hypothesis_id=hypothesis.id,
                    # KeyError here is impossible: citations were validated against
                    # exactly these references before this function was reached.
                    evidence_item_id=evidence_ids[ref],
                )
            )
            citations += 1
    session.flush()

    assessment = _persist_impact(session, state.run_id, state.impact)
    governance_counts = _persist_governance(session, state, occurred_at=occurred_at)

    return PersistedInvestigation(
        evidence_items=len(state.evidence),
        hypotheses=len(state.hypotheses.hypotheses),
        citations=citations,
        impact_assessment_id=assessment.id,
        interventions=governance_counts[0],
        policy_evaluations=governance_counts[1],
        approval_requests=governance_counts[2],
    )


def _persist_governance(
    session: Session, state: WorkflowState, *, occurred_at: datetime
) -> tuple[int, int, int]:
    """Interventions, their policy evaluations, and any approval requests.

    **Every intervention is persisted, including the denied one.** A refusal that left
    no row would be indistinguishable from a proposal that was never made, and the
    ability to answer "what did it want to do, and what stopped it?" is most of what
    the governance tables are for.

    Ordering matters and is not incidental: `policy_evaluations` has a unique foreign
    key to `interventions`, and `approval_requests` one to `policy_evaluations`, so the
    chain from action to authorisation is a schema guarantee rather than a convention.

    **Nothing here executes anything.** No `action_records` row is written, because
    nothing acted -- that is Session 6.
    """
    decisions = {item.draft.title: item.outcome for item in state.policy_decisions}
    interventions = evaluations = approvals = 0

    for rank, ranked in enumerate(state.interventions, start=1):
        row = orm.Intervention(
            id=new_id(),
            run_id=state.run_id,
            rank=rank,
            title=ranked.draft.title,
            action_type=ranked.draft.action,
            rationale=ranked.draft.rationale,
            target_ref=ranked.draft.target_ref,
            expected_value=ranked.score.expected_value,
            effort_score=ranked.score.effort_score,
            risk_score=ranked.score.risk_score,
            composite_score=ranked.score.composite_score,
        )
        session.add(row)
        session.flush()
        interventions += 1

        outcome = decisions.get(ranked.draft.title)
        if outcome is None:
            continue

        evaluation = gov_orm.PolicyEvaluation(
            id=new_id(),
            intervention_id=row.id,
            policy_version=outcome.policy_version,
            risk_tier=int(outcome.risk_tier),
            decision=outcome.decision,
            matched_rules=list(outcome.matched_rules),
            reason=outcome.reason,
            evaluated_at=occurred_at,
        )
        session.add(evaluation)
        session.flush()
        evaluations += 1

        if outcome.decision is PolicyDecision.REQUIRE_APPROVAL:
            create_approval_request(
                session,
                policy_evaluation_id=evaluation.id,
                run_id=state.run_id,
                requested_by=POLICY_ACTOR,
                occurred_at=occurred_at,
            )
            approvals += 1

    return interventions, evaluations, approvals


def _persist_impact(session: Session, run_id: UUID, impact: PipelineImpact) -> orm.ImpactAssessment:
    assessment = orm.ImpactAssessment(
        id=new_id(),
        run_id=run_id,
        method_version=impact.method_version,
        pipeline_value=impact.pipeline_value,
        weighted_value=impact.weighted_value,
        at_risk_value=impact.at_risk_value,
        currency=impact.currency,
        inputs=impact.inputs,
        # Always. The `MODEL` member of this enum exists so a violation of rule 9
        # would be visible in the data, not so it is permitted.
        computed_by=ComputedBy.DETERMINISTIC,
    )
    session.add(assessment)
    session.flush()
    return assessment
