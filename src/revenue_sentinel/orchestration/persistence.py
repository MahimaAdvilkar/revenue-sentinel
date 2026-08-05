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

from revenue_sentinel.analytics.pipeline_impact import PipelineImpact
from revenue_sentinel.core.ids import hypothesis_ref, new_id
from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import investigation as orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import ComputedBy, TrustLevel
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
    return PersistedInvestigation(
        evidence_items=len(state.evidence),
        hypotheses=len(state.hypotheses.hypotheses),
        citations=citations,
        impact_assessment_id=assessment.id,
    )


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
