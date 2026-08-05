"""Tool-call, model-call, cost, budget, and audit tables.

`cost_entries.amount_usd` is `NUMERIC(12, 6)` and carries a `pricing_version`, so a
published price change does not silently rewrite what a historical run cost.

Cache tokens are separate columns from input tokens. Collapsing them would hide the
largest single lever on spend and make the Session 7 cache-hit assertion
unwritable.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from revenue_sentinel.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    cost_amount,
    digest,
    json_object,
    money,
    pg_enum,
    short_text,
    span_id_col,
    timestamp_tz,
    trace_id_col,
    uuid_fk,
    uuid_pk,
)
from revenue_sentinel.domain.enums import (
    BudgetPeriod,
    BudgetScope,
    CostType,
    ToolCallStatus,
)


class ToolCall(Base, CreatedAtMixin):
    __tablename__ = "tool_calls"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    node_name: Mapped[str] = mapped_column(sa.String(64))
    tool_name: Mapped[short_text]
    args: Mapped[json_object]
    result_digest: Mapped[digest]
    status: Mapped[ToolCallStatus] = mapped_column(pg_enum(ToolCallStatus, "tool_call_status"))
    duration_ms: Mapped[int] = mapped_column(sa.Integer)
    trace_id: Mapped[trace_id_col]
    span_id: Mapped[span_id_col]
    parent_span_id: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)

    __table_args__ = (
        sa.CheckConstraint("duration_ms >= 0", name="duration_non_negative"),
        sa.Index("ix_tool_calls_run_id_tool_name", "run_id", "tool_name"),
        sa.Index("ix_tool_calls_trace_id", "trace_id"),
    )


class ModelCall(Base, CreatedAtMixin):
    __tablename__ = "model_calls"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    node_name: Mapped[str] = mapped_column(sa.String(64))
    model_id: Mapped[short_text]
    effort: Mapped[str] = mapped_column(sa.String(16))
    input_tokens: Mapped[int] = mapped_column(sa.Integer)
    output_tokens: Mapped[int] = mapped_column(sa.Integer)
    cache_read_tokens: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("0"))
    cache_write_tokens: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("0"))
    latency_ms: Mapped[int] = mapped_column(sa.Integer)
    stop_reason: Mapped[str] = mapped_column(sa.String(32))
    trace_id: Mapped[trace_id_col]
    span_id: Mapped[span_id_col]
    # True when the response came from a fixture rather than the API. Mirrors the
    # `is_simulated` convention: honesty about provenance is a schema property, not a
    # convention someone has to remember. See ADR-0013.
    is_replay: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false(), default=False
    )

    __table_args__ = (
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 "
            "AND cache_read_tokens >= 0 AND cache_write_tokens >= 0",
            name="tokens_non_negative",
        ),
        sa.CheckConstraint("latency_ms >= 0", name="latency_non_negative"),
        sa.Index("ix_model_calls_run_id_node_name", "run_id", "node_name"),
    )


class CostEntry(Base, CreatedAtMixin):
    """Every dollar traces to exactly one call."""

    __tablename__ = "cost_entries"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    model_call_id: Mapped[uuid_fk | None] = mapped_column(
        sa.ForeignKey("model_calls.id", ondelete="CASCADE"), nullable=True
    )
    tool_call_id: Mapped[uuid_fk | None] = mapped_column(
        sa.ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=True
    )
    cost_type: Mapped[CostType] = mapped_column(pg_enum(CostType, "cost_type"))
    amount_usd: Mapped[cost_amount]
    pricing_version: Mapped[str] = mapped_column(sa.String(32))
    recorded_at: Mapped[timestamp_tz]

    __table_args__ = (
        # Exactly one source, enforced in SQL: an unattributable cost entry would
        # make the per-incident breakdown in the dashboard a guess.
        sa.CheckConstraint(
            "(model_call_id IS NULL) <> (tool_call_id IS NULL)",
            name="exactly_one_source",
        ),
        sa.CheckConstraint("amount_usd >= 0", name="amount_non_negative"),
        sa.Index("ix_cost_entries_run_id_cost_type", "run_id", "cost_type"),
    )


class Budget(Base, TimestampMixin):
    __tablename__ = "budgets"

    id: Mapped[uuid_pk]
    scope: Mapped[BudgetScope] = mapped_column(pg_enum(BudgetScope, "budget_scope"))
    scope_ref: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    period: Mapped[BudgetPeriod] = mapped_column(pg_enum(BudgetPeriod, "budget_period"))
    limit_usd: Mapped[money]
    consumed_usd: Mapped[money] = mapped_column(server_default=sa.text("0"))
    hard_stop: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.true())

    __table_args__ = (
        sa.UniqueConstraint(
            "scope", "scope_ref", "period", name="uq_budgets_scope_scope_ref_period"
        ),
        sa.CheckConstraint("limit_usd >= 0 AND consumed_usd >= 0", name="amounts_non_negative"),
    )


class AuditEvent(Base, CreatedAtMixin):
    """Append-only."""

    __tablename__ = "audit_events"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid_fk | None] = mapped_column(
        sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=True
    )
    incident_id: Mapped[uuid_fk | None] = mapped_column(
        sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True
    )
    event_type: Mapped[short_text]
    actor: Mapped[short_text]
    payload: Mapped[json_object]
    occurred_at: Mapped[timestamp_tz]

    __table_args__ = (
        # Powers the incident timeline in one query -- see docs/data-model.md §4.
        sa.Index("ix_audit_events_incident_id_occurred_at", "incident_id", "occurred_at"),
        sa.Index("ix_audit_events_run_id_occurred_at", "run_id", "occurred_at"),
    )
