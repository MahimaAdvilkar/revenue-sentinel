"""Strategy Agent -- drafts interventions; does not rank them.

The same split as `analyst.py`, and for the same reason: drafting is judgement over an
ambiguous situation, and ranking is arithmetic. One is a job for a model and the other
is not (rule 9, ADR-0003).

The model contributes a title, an action type, a rationale, and two **bands**. It
supplies no money, no scores, and no ordering. `rank_drafts` below hands the bands to
`analytics/intervention_scoring.py`, which `import-linter` R3 forbids from importing
anything in `intelligence/` or `agents/` -- so the ranking is beyond a model's reach
structurally, not by convention.

The model is also free to propose actions the system may not perform. That is
deliberate: see `ProposedAction`. Nothing here filters them out, because a refusal the
system never records is a refusal nobody can audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from revenue_sentinel.analytics.intervention_scoring import (
    ScoredIntervention,
    rank,
    score_intervention,
)
from revenue_sentinel.intelligence.ports import LLMClient, LLMRequest, LLMResponse
from revenue_sentinel.intelligence.prompts import STRATEGIST_SYSTEM_PROMPT, render_strategy_context
from revenue_sentinel.intelligence.schemas import (
    TOP_INTERVENTIONS,
    InterventionDraft,
    InterventionSet,
)

STRATEGY_NODE_NAME = "draft_interventions"


def draft_interventions(
    *,
    incident_block: str,
    hypotheses: tuple[tuple[str, str, tuple[str, ...]], ...],
    llm: LLMClient,
    model_id: str,
    effort: str,
) -> LLMResponse[InterventionSet]:
    """Ask for three to five candidate interventions.

    The hypotheses are rendered into delimited, escaped blocks. They are model-produced
    rather than ingested, but they were written *from* untrusted evidence, so they are
    contained on the way to the next node as well.
    """
    return llm.complete_structured(
        LLMRequest(
            node_name=STRATEGY_NODE_NAME,
            system_prompt=STRATEGIST_SYSTEM_PROMPT,
            user_content=render_strategy_context(
                incident_block=incident_block, hypotheses=hypotheses
            ),
            output_schema=InterventionSet,
            model_id=model_id,
            effort=effort,
        )
    )


@dataclass(frozen=True, slots=True)
class RankedIntervention:
    """A draft and the figures computed for it.

    Both are needed downstream: the title, rationale and target come from the draft;
    every number comes from the score. Pairing them here means no caller has to
    re-derive which score belongs to which draft, and no caller is tempted to read a
    number off the draft -- there are none there to read.
    """

    draft: InterventionDraft
    score: ScoredIntervention


def rank_drafts(
    drafts: InterventionSet,
    *,
    at_risk_value: Decimal,
    weighted_value: Decimal,
    keep: int = TOP_INTERVENTIONS,
) -> tuple[RankedIntervention, ...]:
    """Score every draft, order by composite, keep the top `keep`.

    The order this returns **is** the persisted rank order. It comes from
    `analytics/`, never from the order the model happened to write them in.
    """
    by_title = {draft.title: draft for draft in drafts.interventions}

    scored = tuple(
        score_intervention(
            title=draft.title,
            action=draft.action,
            recovery=draft.recovery,
            effort=draft.effort,
            at_risk_value=at_risk_value,
            weighted_value=weighted_value,
            fields_changed=frozenset(draft.fields_changed),
        )
        for draft in drafts.interventions
    )

    return tuple(
        RankedIntervention(draft=by_title[item.title], score=item) for item in rank(scored)[:keep]
    )
