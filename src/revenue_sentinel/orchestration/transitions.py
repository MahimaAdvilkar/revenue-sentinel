"""The transition recorder.

**Our tables are the source of truth, not LangGraph's checkpointer** (ADR-0002 rule 2).
A transition row is written *before* the destination node executes, so a crash inside
a node leaves a record that the node was entered -- which is the difference between a
run you can investigate and one you can only guess about.

`(run_id, sequence)` is UNIQUE and sequences start at 0 with no gaps, so the ordering
is total and a missing row is detectable rather than invisible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.ids import new_id
from revenue_sentinel.db.models import workflow as orm

GRAPH_ENTRY = "__start__"
GRAPH_EXIT_NODE = "__end__"


@dataclass(slots=True)
class TransitionRecorder:
    """Writes one `workflow_transitions` row per node entry."""

    session: Session
    run_id: UUID
    occurred_at: datetime
    _sequence: int = 0

    def record(
        self,
        *,
        from_node: str | None,
        to_node: str,
        state_digest: str,
        duration_ms: int = 0,
        edge_predicate: str | None = None,
    ) -> orm.WorkflowTransition:
        transition = orm.WorkflowTransition(
            id=new_id(),
            run_id=self.run_id,
            sequence=self._sequence,
            from_node=from_node,
            to_node=to_node,
            edge_predicate=edge_predicate,
            occurred_at=self.occurred_at,
            duration_ms=duration_ms,
            state_digest=state_digest,
        )
        self.session.add(transition)
        self.session.flush()
        self._sequence += 1
        return transition

    @property
    def next_sequence(self) -> int:
        return self._sequence


def transitions_for_run(session: Session, run_id: UUID) -> list[orm.WorkflowTransition]:
    """Run history in order. The replay view reads exactly this."""
    return list(
        session.scalars(
            sa.select(orm.WorkflowTransition)
            .where(orm.WorkflowTransition.run_id == run_id)
            .order_by(orm.WorkflowTransition.sequence)
        ).all()
    )
