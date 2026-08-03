"""Workflow runs, transitions, and agent decisions.

`WorkflowTransition` is append-only and `(run_id, sequence)` is UNIQUE: transition
ordering is total and gapless, and there is no way to move the workflow without
leaving a record.

`AgentDecision.model_call_id` is nullable **by design**. It is `NULL` for every
deterministic agent, so `WHERE model_call_id IS NULL` is a one-line proof of which
agents never touched a model -- the evaluation suite's `no_llm_arithmetic` check
(Session 8) is exactly that query.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.base import (
    Digest,
    DomainModel,
    NonEmptyStr,
    UtcDatetime,
)
from revenue_sentinel.domain.enums import WorkflowStatus


class WorkflowRun(DomainModel):
    """One execution of the investigation graph against one incident."""

    id: UUID
    incident_id: UUID
    graph_version: NonEmptyStr
    status: WorkflowStatus
    current_node: str | None = None
    started_at: UtcDatetime
    ended_at: UtcDatetime | None = None
    checkpoint_ref: str | None = None

    @model_validator(mode="after")
    def _end_follows_start(self) -> WorkflowRun:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at precedes started_at")
        return self


class WorkflowTransition(DomainModel):
    """A single edge traversal, written *before* the destination node runs."""

    id: UUID
    run_id: UUID
    sequence: int = Field(ge=0)
    from_node: str | None = None
    to_node: NonEmptyStr
    edge_predicate: str | None = None
    occurred_at: UtcDatetime
    duration_ms: int = Field(ge=0)
    state_digest: Digest


class AgentDecision(DomainModel):
    """What an agent concluded, and whether a model was involved."""

    id: UUID
    run_id: UUID
    agent_name: NonEmptyStr
    decision_type: NonEmptyStr
    rationale: str
    inputs_digest: Digest
    output: JSONObject
    model_call_id: UUID | None = None

    @property
    def used_a_model(self) -> bool:
        """True only for the LLM-backed agents. See ADR-0003."""
        return self.model_call_id is not None
