"""Revenue Analyst -- two responsibilities, deliberately split.

**Hypotheses (LLM).** Evidence-backed explanations, each citing evidence ids that
exist in state. Genuine reasoning over incomplete information.

**Impact (deterministic).** Delegated to `analytics/pipeline_impact.py`. No model
sees the arithmetic, and `import-linter` R3 makes it impossible for one to: `analytics/`
cannot import `intelligence/` or `agents/`, so the calculator is unreachable from the
model layer even by accident.

The two live in one module because they are one agent in the architecture, and are
two functions because they are two different kinds of claim. The system prompt tells
the model not to produce monetary figures; this structure means it could not matter
if it did -- nothing reads them.
"""

from __future__ import annotations

from decimal import Decimal

from revenue_sentinel.agents.citations import validate_citations
from revenue_sentinel.analytics.pipeline_impact import PipelineImpact, calculate_pipeline_impact
from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.enums import OpportunityStage
from revenue_sentinel.intelligence.ports import LLMClient, LLMRequest, LLMResponse
from revenue_sentinel.intelligence.prompts import ANALYST_SYSTEM_PROMPT, render_evidence_bundle
from revenue_sentinel.intelligence.schemas import HypothesisSet

HYPOTHESES_NODE_NAME = "generate_hypotheses"
IMPACT_NODE_NAME = "calculate_impact"


def generate_hypotheses(
    evidence: tuple[tuple[str, str, JSONObject], ...],
    *,
    llm: LLMClient,
    model_id: str,
    effort: str,
) -> LLMResponse[HypothesisSet]:
    """Ask for candidate explanations, citing the evidence provided.

    The evidence is rendered into delimited `<evidence>` blocks with escaped content;
    it never touches the system prompt (rule 14).
    """
    user_content = render_evidence_bundle(evidence)

    return llm.complete_structured(
        LLMRequest(
            node_name=HYPOTHESES_NODE_NAME,
            system_prompt=ANALYST_SYSTEM_PROMPT,
            user_content=user_content,
            output_schema=HypothesisSet,
            model_id=model_id,
            effort=effort,
        )
    )


def accept_hypotheses(hypotheses: HypothesisSet, known_refs: frozenset[str]) -> HypothesisSet:
    """Validate citations, then return the set unchanged.

    Separate from `generate_hypotheses` so the check can be exercised against any
    hypothesis set, including one loaded from a fixture, without a client.
    """
    validate_citations(hypotheses, known_refs)
    return hypotheses


def assess_impact(
    *,
    amount: Decimal,
    currency: str,
    probability: Decimal,
    days_inactive: int,
    stage: OpportunityStage,
    usage_growth: Decimal,
) -> PipelineImpact:
    """Compute pipeline impact. **No model is involved, by construction.**

    A thin pass-through to `analytics/`, and that is the point: the analyst *requests*
    a calculation it cannot perform. The corresponding `agent_decisions` row carries
    `model_call_id = NULL`, which is the query the Session 8 `no_llm_arithmetic` check
    runs.
    """
    return calculate_pipeline_impact(
        amount=amount,
        currency=currency,
        probability=probability,
        days_inactive=days_inactive,
        stage=stage,
        usage_growth=usage_growth,
    )
