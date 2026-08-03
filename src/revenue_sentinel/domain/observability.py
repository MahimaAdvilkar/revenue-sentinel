"""Ledgers: tool calls, model calls, cost, budgets, and the audit trail.

Cost is `NUMERIC(12, 6)` and carries a `pricing_version`, so a published price
change does not silently rewrite what a historical run cost.

Cache tokens are recorded separately from input tokens. Collapsing them would hide
the single largest lever on spend and make the Session 7 cache-hit assertion
impossible to write.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import Field, model_validator

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.base import (
    CostAmount,
    Digest,
    DomainModel,
    Money,
    NonEmptyStr,
    SpanId,
    TraceId,
    UtcDatetime,
)
from revenue_sentinel.domain.enums import (
    BudgetPeriod,
    BudgetScope,
    CostType,
    ToolCallStatus,
)


class ToolCall(DomainModel):
    """One MCP tool invocation. Arguments are stored; results are digested."""

    id: UUID
    run_id: UUID
    node_name: NonEmptyStr
    tool_name: NonEmptyStr
    args: JSONObject
    result_digest: Digest
    status: ToolCallStatus
    duration_ms: int = Field(ge=0)
    trace_id: TraceId
    span_id: SpanId
    parent_span_id: SpanId | None = None


class ModelCall(DomainModel):
    """One Claude API call."""

    id: UUID
    run_id: UUID
    node_name: NonEmptyStr
    model_id: NonEmptyStr
    effort: NonEmptyStr
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cache_write_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    stop_reason: NonEmptyStr
    trace_id: TraceId
    span_id: SpanId


class CostEntry(DomainModel):
    """A billed line item, attributable to exactly one call."""

    id: UUID
    run_id: UUID
    model_call_id: UUID | None = None
    tool_call_id: UUID | None = None
    cost_type: CostType
    amount_usd: CostAmount
    pricing_version: NonEmptyStr
    recorded_at: UtcDatetime

    @model_validator(mode="after")
    def _exactly_one_source(self) -> CostEntry:
        """Every dollar traces to one call. An unattributable cost entry would make
        the per-incident breakdown in the dashboard a guess."""
        sources = [self.model_call_id, self.tool_call_id]
        if sum(source is not None for source in sources) != 1:
            raise ValueError("a cost entry names exactly one of model_call_id or tool_call_id")
        return self


class Budget(DomainModel):
    """A spend ceiling at one of three scopes."""

    id: UUID
    scope: BudgetScope
    scope_ref: str | None = None
    period: BudgetPeriod
    limit_usd: Money
    consumed_usd: Money
    hard_stop: bool

    @property
    def remaining_usd(self) -> Money:
        return max(self.limit_usd - self.consumed_usd, Decimal("0.00"))

    @property
    def is_exhausted(self) -> bool:
        return self.consumed_usd >= self.limit_usd

    @model_validator(mode="after")
    def _scoped_budgets_name_their_scope(self) -> Budget:
        if self.scope is not BudgetScope.GLOBAL and not self.scope_ref:
            raise ValueError(f"a {self.scope} budget requires a scope_ref")
        return self


class AuditEvent(DomainModel):
    """An append-only record of something that happened.

    `actor` is `system`, `agent:<name>`, or `user:<id>` -- a machine-readable answer
    to "who did this", which a free-text field would not be.
    """

    id: UUID
    run_id: UUID | None = None
    incident_id: UUID | None = None
    event_type: NonEmptyStr
    actor: NonEmptyStr
    payload: JSONObject
    occurred_at: UtcDatetime
