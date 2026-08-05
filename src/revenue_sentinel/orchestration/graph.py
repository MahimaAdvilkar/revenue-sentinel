"""The investigation graph.

LangGraph owns topology, routing, and checkpointing. It owns nothing else (ADR-0002).

Everything a node must not do -- record a transition, write a model call, write an
agent decision -- happens in `_instrument`, the wrapper this module puts around each
node. That is what keeps node bodies thin without losing the audit trail: the
discipline lives in one place instead of being asked of every node author.

**The transition is written before the wrapped body runs.** A crash inside a node
therefore leaves a record that the node was entered, which is the difference between a
run you can investigate and one you can only guess about.

Checkpointing uses `InMemorySaver` (ADR-0012). Session 3 has no interrupt and no
resume-across-restart; `workflow_transitions` is the durable record either way. The
Postgres saver arrives in Session 6, when a human approval genuinely has to survive
the process exiting.
"""

from __future__ import annotations

import time
from typing import Protocol, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session

from revenue_sentinel.orchestration import persistence
from revenue_sentinel.orchestration.nodes import (
    EVIDENCE_NODE,
    HYPOTHESES_NODE,
    IMPACT_NODE,
    NODE_FUNCTIONS,
    PLAN_NODE,
    NodeContext,
)
from revenue_sentinel.orchestration.state import WorkflowState
from revenue_sentinel.orchestration.transitions import GRAPH_ENTRY, TransitionRecorder

GRAPH_VERSION = "investigation/v1"

# Which agent each node belongs to, for `agent_decisions.agent_name`.
_AGENT_BY_NODE = {
    PLAN_NODE: "investigation_planner",
    EVIDENCE_NODE: "research_agent",
    HYPOTHESES_NODE: "revenue_analyst",
    IMPACT_NODE: "revenue_analyst",
}


class NodeCallable(Protocol):
    """The shape LangGraph requires of a node.

    The parameter must be named `state`: LangGraph's internal `_Node` protocol
    declares `__call__(self, state: NodeInputT)`, and a bare
    `Callable[[GraphState], ...]` has a positional-only parameter, which does not
    satisfy it. Declaring the protocol here keeps `add_node` type-checked rather than
    suppressed.
    """

    def __call__(self, state: GraphState) -> dict[str, WorkflowState]: ...


class GraphState(TypedDict):
    """LangGraph's view of the world: one field holding ours.

    Keeping our state as a single opaque value means LangGraph never becomes the
    place state is *defined* -- it only carries it between nodes.
    """

    state: WorkflowState


def _instrument(
    node_name: str,
    session: Session,
    recorder: TransitionRecorder,
    context: NodeContext,
    previous_node: str | None,
) -> NodeCallable:
    """Wrap a node with transition recording and decision persistence."""
    body = NODE_FUNCTIONS[node_name]

    def run(state: GraphState) -> dict[str, WorkflowState]:
        current = state["state"]

        # Before the body: the transition into this node.
        recorder.record(
            from_node=previous_node or GRAPH_ENTRY,
            to_node=node_name,
            state_digest=current.digest(),
        )

        started = time.perf_counter()
        result = body(current, context)
        duration_ms = int((time.perf_counter() - started) * 1000)

        model_call_id = None
        if result.llm_response is not None:
            model_call = persistence.record_model_call(
                session,
                run_id=current.run_id,
                node_name=node_name,
                response=result.llm_response,
            )
            model_call_id = model_call.id

        persistence.record_agent_decision(
            session,
            run_id=current.run_id,
            agent_name=_AGENT_BY_NODE[node_name],
            decision_type=node_name,
            rationale=f"{node_name} completed in {duration_ms}ms",
            inputs={"state_digest": current.digest()},
            output={"state_digest": result.state.digest()},
            model_call_id=model_call_id,
        )

        return {"state": result.state}

    return run


def build_graph(
    session: Session, recorder: TransitionRecorder, context: NodeContext
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    """Wire the four nodes into a linear graph and compile it."""
    builder = StateGraph(GraphState)

    order = (PLAN_NODE, EVIDENCE_NODE, HYPOTHESES_NODE, IMPACT_NODE)
    for index, node_name in enumerate(order):
        previous = order[index - 1] if index > 0 else None
        builder.add_node(node_name, _instrument(node_name, session, recorder, context, previous))

    builder.add_edge(START, PLAN_NODE)
    builder.add_edge(PLAN_NODE, EVIDENCE_NODE)
    builder.add_edge(EVIDENCE_NODE, HYPOTHESES_NODE)
    builder.add_edge(HYPOTHESES_NODE, IMPACT_NODE)
    builder.add_edge(IMPACT_NODE, END)

    return builder.compile(checkpointer=InMemorySaver())
