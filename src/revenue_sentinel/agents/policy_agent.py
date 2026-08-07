"""Policy & Risk Agent -- deterministic, and thin by design.

There is no model here and no prompt. The agent's entire job is to hand each ranked
intervention to `governance/policy_engine.py` and carry back the outcome, which is why
this module is short: the decision logic belongs to governance, and duplicating any of
it here would create a second place a rule could be changed.

It exists as an agent rather than as a call inside the node because
`docs/agent-architecture.md` lists it as one of the nine agents, and because keeping it
here makes the boundary visible -- `agents/` cannot import `db/` (R5), so this cannot
accidentally start persisting its own decisions.

**Nothing it returns causes anything to happen.** Session 5 records decisions; nothing
executes. The write tools remain unwired from the graph.
"""

from __future__ import annotations

from dataclasses import dataclass

from revenue_sentinel.governance.outcomes import PolicyOutcome
from revenue_sentinel.governance.policy_engine import PolicyRequest, evaluate
from revenue_sentinel.intelligence.schemas import InterventionDraft

POLICY_NODE_NAME = "evaluate_policy"
POLICY_ACTOR = "agent:policy_and_risk"


@dataclass(frozen=True, slots=True)
class EvaluatedIntervention:
    """One intervention and the decision made about it."""

    draft: InterventionDraft
    outcome: PolicyOutcome


def evaluate_interventions(
    drafts: tuple[InterventionDraft, ...],
) -> tuple[EvaluatedIntervention, ...]:
    """One decision per intervention, in the order given.

    Order is preserved because it is the rank order `analytics/` produced, and a
    reordering here would silently change which intervention the dashboard calls
    "first recommended".
    """
    return tuple(
        EvaluatedIntervention(
            draft=draft,
            outcome=evaluate(
                PolicyRequest(
                    action=draft.action,
                    target_ref=draft.target_ref,
                    fields_changed=frozenset(draft.fields_changed),
                    actor=POLICY_ACTOR,
                )
            ),
        )
        for draft in drafts
    )
