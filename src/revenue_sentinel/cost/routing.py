"""Which model runs at which call site. A frozen table, not a decision.

Routing is data because it has to be reproducible: the same node must reach the same
model at the same effort on every run, or a replayed workflow costs a different amount
than the one it replays. Nothing here consults a model to choose a model.

The table mirrors `docs/cost-governance.md` §3, and a test asserts the two agree. A
routing table that drifts from its documentation is a cost model nobody can predict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from revenue_sentinel.core.errors import RevenueSentinelError

ROUTING_VERSION: Final = "routing/v1"


@dataclass(frozen=True, slots=True)
class Route:
    model_id: str
    effort: str
    max_output_tokens: int
    """The reservation ceiling. Also the real cap sent to the API, so the worst-case
    bound is a bound rather than a hope."""


class UnroutedCallSiteError(RevenueSentinelError):
    """An LLM call site with no routing entry.

    Refused rather than defaulted. A new node quietly inheriting the most expensive
    model is how cost surprises happen.
    """

    def __init__(self, node_name: str) -> None:
        super().__init__(
            f"{node_name!r} has no routing entry. Add one to ROUTING_TABLE and to "
            f"docs/cost-governance.md §3 -- a call site must not default to a model."
        )


ROUTING_TABLE: Final[dict[str, Route]] = {
    "plan_investigation": Route("claude-opus-5", "high", 2_000),
    "collect_evidence": Route("claude-opus-5", "medium", 1_000),
    "generate_hypotheses": Route("claude-opus-5", "high", 3_000),
    "draft_interventions": Route("claude-opus-5", "high", 3_000),
}
"""Four LLM call sites. `calculate_impact` and `evaluate_policy` are absent because they
are deterministic -- they have no model to route, which is the point of rule 9."""


def route_for(node_name: str) -> Route:
    route = ROUTING_TABLE.get(node_name)
    if route is None:
        raise UnroutedCallSiteError(node_name)
    return route
