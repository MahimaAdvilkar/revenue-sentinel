"""The four node bodies.

**Thin, by rule** (ADR-0002). A node reads typed fields off `WorkflowState`, calls
exactly one service in `agents/` or `analytics/`, and returns new state. It does not
persist, does not audit, does not query, and does not decide anything.

That is why this module imports no `db`, no `sqlalchemy`, and no session -- a fact a
test asserts against the AST. Persistence and transition recording happen in the
wrapper in `graph.py`, which is orchestration's job, not the node's.

The services each node needs are supplied by `NodeContext` rather than constructed
here, so every node is callable in a test with a stub client and no graph running.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from revenue_sentinel.agents import analyst, planner, researcher
from revenue_sentinel.agents.ports import EvidenceSource
from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.intelligence.ports import LLMClient, LLMResponse
from revenue_sentinel.orchestration.state import WorkflowState

PLAN_NODE = "plan_investigation"
EVIDENCE_NODE = "collect_evidence"
HYPOTHESES_NODE = "generate_hypotheses"
IMPACT_NODE = "calculate_impact"

NODE_SEQUENCE = (PLAN_NODE, EVIDENCE_NODE, HYPOTHESES_NODE, IMPACT_NODE)


@dataclass(frozen=True, slots=True)
class NodeContext:
    """Services a node may use. Injected, never constructed inside a node."""

    llm: LLMClient
    evidence_source: EvidenceSource
    model_id: str
    effort: str


@dataclass(frozen=True, slots=True)
class NodeResult:
    """New state, plus the model call that produced it if there was one.

    `llm_response` is `None` for deterministic nodes. That is what the wrapper writes
    as `agent_decisions.model_call_id = NULL`, and it is the query the Session 8
    `no_llm_arithmetic` check runs.
    """

    state: WorkflowState
    llm_response: LLMResponse[BaseModel] | None = None


def plan_investigation(state: WorkflowState, context: NodeContext) -> NodeResult:
    response = planner.plan_investigation(
        planner.PlanningInput(
            incident=state.incident,
            account=state.account,
            opportunity=state.opportunity,
            days_inactive=state.days_inactive,
            usage_growth=Decimal(state.usage_growth),
        ),
        llm=context.llm,
        model_id=context.model_id,
        effort=context.effort,
    )
    return NodeResult(state.with_plan(response.output), response)


def collect_evidence(state: WorkflowState, context: NodeContext) -> NodeResult:
    if state.plan is None:
        raise ValueError("collect_evidence requires a plan")

    response = researcher.select_sources(
        state.plan, llm=context.llm, model_id=context.model_id, effort=context.effort
    )
    gathered = researcher.gather(
        response.output,
        source=context.evidence_source,
        account_id=state.account.id,
        opportunity_id=state.opportunity.id,
    )
    return NodeResult(state.with_evidence(gathered), response)


def generate_hypotheses(state: WorkflowState, context: NodeContext) -> NodeResult:
    bundle: tuple[tuple[str, str, JSONObject], ...] = tuple(
        (item.evidence_ref, item.record.source_system.value, item.record.content)
        for item in state.evidence
    )
    response = analyst.generate_hypotheses(
        bundle, llm=context.llm, model_id=context.model_id, effort=context.effort
    )
    accepted = analyst.accept_hypotheses(response.output, state.known_evidence_refs)
    return NodeResult(state.with_hypotheses(accepted), response)


def calculate_impact(state: WorkflowState, context: NodeContext) -> NodeResult:
    """The one node with no model. See `agents/analyst.py`."""
    impact = analyst.assess_impact(
        amount=state.opportunity.amount,
        currency=state.opportunity.currency,
        probability=state.opportunity.probability,
        days_inactive=state.days_inactive,
        stage=state.opportunity.stage,
        usage_growth=Decimal(state.usage_growth),
    )
    return NodeResult(state.with_impact(impact), None)


NODE_FUNCTIONS = {
    PLAN_NODE: plan_investigation,
    EVIDENCE_NODE: collect_evidence,
    HYPOTHESES_NODE: generate_hypotheses,
    IMPACT_NODE: calculate_impact,
}
