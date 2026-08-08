"""One incident's activity, in order, with what each step cost.

Four append-only tables describe a run from different angles -- `model_calls`,
`tool_calls`, `cost_entries`, `audit_events` -- and none of them alone answers "what
happened, in what order, and what did it cost?". This merges them.

**Nothing is fabricated.** `audit_events` carries no trace or span, so its rows report
`None` rather than an invented id. A timeline that filled in plausible-looking tracing
metadata would be worse than one with gaps, because the gaps are the honest signal that
those rows were never part of a traced call.

Ordering is deterministic: timestamp, then a fixed source rank, then the row id. Identical
timestamps are common here -- the whole run shares one injected `evaluated_at` -- so
without a total order the timeline would shuffle between runs and stop being comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.models import workflow as workflow_orm

SOURCE_RANK: Final[dict[str, int]] = {
    "audit_event": 0,
    "model_call": 1,
    "tool_call": 2,
    "cost_entry": 3,
}
"""Tie-break for identical timestamps. Audit first because a lifecycle transition frames
what follows; cost last because it is a consequence of the call above it."""


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """One row of the merged timeline. `None` means *absent*, never *unknown*."""

    occurred_at: datetime
    source: str
    event_type: str
    detail: str
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    amount_usd: Decimal | None = None
    pricing_version: str | None = None
    integration_status: str | None = None

    @property
    def sort_key(self) -> tuple[datetime, int, str]:
        return (self.occurred_at, SOURCE_RANK[self.source], self.event_type + self.detail)


def incident_timeline(session: Session, *, run_id: UUID) -> list[TimelineEvent]:
    """Every recorded event for one run, merged and totally ordered."""
    events: list[TimelineEvent] = []

    for call in session.scalars(
        sa.select(obs_orm.ModelCall).where(obs_orm.ModelCall.run_id == run_id)
    ).all():
        events.append(
            TimelineEvent(
                occurred_at=call.created_at,
                source="model_call",
                event_type=call.node_name,
                detail=f"{call.model_id} in={call.input_tokens} out={call.output_tokens}"
                + (" [replay]" if call.is_replay else ""),
                trace_id=call.trace_id,
                span_id=call.span_id,
            )
        )

    for tool in session.scalars(
        sa.select(obs_orm.ToolCall).where(obs_orm.ToolCall.run_id == run_id)
    ).all():
        events.append(
            TimelineEvent(
                occurred_at=tool.created_at,
                source="tool_call",
                event_type=tool.tool_name,
                detail=f"{tool.status.value} in {tool.duration_ms}ms",
                trace_id=tool.trace_id,
                span_id=tool.span_id,
                parent_span_id=tool.parent_span_id,
                integration_status="SIMULATED",
            )
        )

    for entry in session.scalars(
        sa.select(obs_orm.CostEntry).where(obs_orm.CostEntry.run_id == run_id)
    ).all():
        events.append(
            TimelineEvent(
                occurred_at=entry.recorded_at,
                source="cost_entry",
                event_type=entry.cost_type.value,
                detail=f"${entry.amount_usd}",
                amount_usd=entry.amount_usd,
                pricing_version=entry.pricing_version,
            )
        )

    # Audit events are **incident**-scoped, not run-scoped: a lifecycle transition
    # belongs to the incident and may precede the run that observes it. Filtering by
    # `run_id` alone silently returns none, which is how this was found.
    incident_id = session.scalar(
        sa.select(workflow_orm.WorkflowRun.incident_id).where(workflow_orm.WorkflowRun.id == run_id)
    )
    for event in session.scalars(
        sa.select(obs_orm.AuditEvent).where(
            sa.or_(
                obs_orm.AuditEvent.run_id == run_id,
                obs_orm.AuditEvent.incident_id == incident_id,
            )
        )
    ).all():
        events.append(
            TimelineEvent(
                occurred_at=event.occurred_at,
                source="audit_event",
                event_type=event.event_type,
                detail=event.actor,
                # No trace or span on audit rows. Reported absent, never invented.
            )
        )

    return sorted(events, key=lambda item: item.sort_key)


def traces_in(events: list[TimelineEvent]) -> set[str]:
    """The distinct traces present. One run should produce exactly one."""
    return {event.trace_id for event in events if event.trace_id is not None}
