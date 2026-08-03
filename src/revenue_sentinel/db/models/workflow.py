"""Incident, workflow run, transition, and agent decision tables.

`workflow_transitions` is append-only and `(run_id, sequence)` is UNIQUE, which makes
run history total and gapless: there is no way to move the workflow without leaving a
record, and no way to leave two records claiming the same position.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from revenue_sentinel.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    digest,
    json_object,
    long_text,
    pg_enum,
    short_text,
    timestamp_tz,
    uuid_fk,
    uuid_pk,
)
from revenue_sentinel.domain.enums import (
    IncidentStatus,
    IncidentType,
    Severity,
    WorkflowStatus,
)


class Incident(Base, TimestampMixin):
    __tablename__ = "incidents"

    id: Mapped[uuid_pk]
    incident_ref: Mapped[short_text] = mapped_column(unique=True, index=True)
    signal_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("signals.id", ondelete="CASCADE"))
    incident_type: Mapped[IncidentType] = mapped_column(pg_enum(IncidentType, "incident_type"))
    status: Mapped[IncidentStatus] = mapped_column(pg_enum(IncidentStatus, "incident_status"))
    severity: Mapped[Severity] = mapped_column(pg_enum(Severity, "severity"))
    account_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("accounts.id", ondelete="CASCADE"))
    opportunity_id: Mapped[uuid_fk | None] = mapped_column(
        sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=True
    )
    opened_at: Mapped[timestamp_tz]
    closed_at: Mapped[timestamp_tz | None] = mapped_column(nullable=True)
    title: Mapped[short_text]

    __table_args__ = (
        sa.CheckConstraint("closed_at IS NULL OR closed_at >= opened_at", name="closure_ordered"),
        sa.Index("ix_incidents_status_opened_at", "status", "opened_at"),
    )


class WorkflowRun(Base, TimestampMixin):
    __tablename__ = "workflow_runs"

    id: Mapped[uuid_pk]
    incident_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("incidents.id", ondelete="CASCADE"))
    graph_version: Mapped[str] = mapped_column(sa.String(32))
    status: Mapped[WorkflowStatus] = mapped_column(pg_enum(WorkflowStatus, "workflow_status"))
    current_node: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    started_at: Mapped[timestamp_tz]
    ended_at: Mapped[timestamp_tz | None] = mapped_column(nullable=True)
    checkpoint_ref: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    __table_args__ = (
        sa.CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="run_ordered"),
        sa.Index("ix_workflow_runs_incident_id_started_at", "incident_id", "started_at"),
    )


class WorkflowTransition(Base, CreatedAtMixin):
    """Append-only. The source of truth for run history."""

    __tablename__ = "workflow_transitions"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(sa.Integer)
    from_node: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    to_node: Mapped[str] = mapped_column(sa.String(64))
    edge_predicate: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    occurred_at: Mapped[timestamp_tz]
    duration_ms: Mapped[int] = mapped_column(sa.Integer)
    state_digest: Mapped[digest]

    __table_args__ = (
        sa.UniqueConstraint("run_id", "sequence", name="uq_workflow_transitions_run_id_sequence"),
        sa.CheckConstraint("sequence >= 0", name="sequence_non_negative"),
        sa.CheckConstraint("duration_ms >= 0", name="duration_non_negative"),
        sa.Index("ix_workflow_transitions_run_id_sequence", "run_id", "sequence"),
    )


class AgentDecision(Base, CreatedAtMixin):
    """`model_call_id` is NULL for every deterministic agent -- see ADR-0003."""

    __tablename__ = "agent_decisions"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    agent_name: Mapped[str] = mapped_column(sa.String(64))
    decision_type: Mapped[str] = mapped_column(sa.String(64))
    rationale: Mapped[long_text]
    inputs_digest: Mapped[digest]
    output: Mapped[json_object]
    model_call_id: Mapped[uuid_fk | None] = mapped_column(
        sa.ForeignKey("model_calls.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (sa.Index("ix_agent_decisions_run_id_agent_name", "run_id", "agent_name"),)
