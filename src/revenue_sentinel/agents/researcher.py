"""Research Agent -- LLM chooses *what* to gather; code gathers it.

Two distinct steps, deliberately separated:

1. **Selection (LLM).** Given the plan, choose which sources to query. The response
   is schema-validated against a closed set of source names and then checked against
   the plan's own sources -- injection defence layer 4. A model that names a source
   the plan did not authorise is rejected, not accommodated.

2. **Retrieval (deterministic).** The selected sources are called through the
   `EvidenceSource` port. Retrieval itself involves no model: the LLM decides *which*
   evidence to gather, never *what the evidence says*.

Evidence references are assigned in retrieval order (`EV-001`, `EV-002`, ...), which
is the plan's order, so they are stable for a given plan rather than dependent on
insertion timing.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from revenue_sentinel.agents.ports import EvidenceRecord, EvidenceSource
from revenue_sentinel.core.errors import StructuredOutputError
from revenue_sentinel.core.ids import evidence_ref
from revenue_sentinel.intelligence.ports import LLMClient, LLMRequest, LLMResponse
from revenue_sentinel.intelligence.prompts import RESEARCHER_SYSTEM_PROMPT
from revenue_sentinel.intelligence.schemas import (
    EvidenceSelection,
    EvidenceSourceName,
    InvestigationPlan,
)

NODE_NAME = "collect_evidence"


@dataclass(frozen=True, slots=True)
class GatheredEvidence:
    """One retrieved record with its assigned reference."""

    evidence_ref: str
    record: EvidenceRecord


def select_sources(
    plan: InvestigationPlan, *, llm: LLMClient, model_id: str, effort: str
) -> LLMResponse[EvidenceSelection]:
    """Ask the researcher which of the plan's sources to query.

    Raises:
        StructuredOutputError: if the selection names a source the plan did not
            authorise. The schema constrains the vocabulary; this constrains it to
            *this* investigation.
    """
    lines = [f"{step.order}. {step.source.value} - {step.objective}" for step in plan.steps]
    user_content = "<plan>\n" + "\n".join(lines) + f"\n</plan>\n\n{plan.rationale}"

    response = llm.complete_structured(
        LLMRequest(
            node_name=NODE_NAME,
            system_prompt=RESEARCHER_SYSTEM_PROMPT,
            user_content=user_content,
            output_schema=EvidenceSelection,
            model_id=model_id,
            effort=effort,
        )
    )

    try:
        response.output.validate_against_plan(plan.permitted_sources)
    except ValueError as exc:
        raise StructuredOutputError(f"{NODE_NAME}: {exc}") from exc

    return response


def gather(
    selection: EvidenceSelection,
    *,
    source: EvidenceSource,
    account_id: UUID,
    opportunity_id: UUID,
) -> tuple[GatheredEvidence, ...]:
    """Execute the selected requests. Deterministic -- no model involved."""
    dispatch = {
        EvidenceSourceName.CRM_OPPORTUNITY: lambda: source.get_opportunity(opportunity_id),
        EvidenceSourceName.CRM_ACTIVITIES: lambda: source.list_account_activities(account_id),
        EvidenceSourceName.PRODUCT_USAGE: lambda: source.get_usage_summary(account_id),
        EvidenceSourceName.ENGAGEMENT: lambda: source.get_email_activity(account_id),
        EvidenceSourceName.SUPPORT: lambda: source.get_open_issues(account_id),
    }

    gathered: list[GatheredEvidence] = []
    for request in selection.requests:
        # One call may yield several distinct facts -- two usage weeks are two pieces
        # of evidence, citable separately. References are assigned across the flattened
        # sequence so they stay contiguous.
        for record in dispatch[request.source]():
            gathered.append(
                GatheredEvidence(evidence_ref=evidence_ref(len(gathered) + 1), record=record)
            )
    return tuple(gathered)
