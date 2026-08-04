"""Event sources -- **SIMULATED**.

> **INGESTION_STATUS = "SIMULATED".** This module does not talk to any external
> system. It reads the locally seeded GTM mirror tables and replays those rows as
> though a source adapter had delivered them. It is a simulation of ingestion, not
> ingestion (rule 5).

## What changes when this becomes real

Session 4 introduces `integrations/ports/` and fixture-backed adapters, and Session 4
or later would replace this module with a poller or webhook receiver per source
system. Three things change and the rest of the pipeline does not:

1. `read_source_events()` calls an adapter instead of a repository.
2. `source_event_id` comes from the provider's own event identifier rather than
   being derived from our row identity.
3. `received_at` becomes the moment we actually received the payload rather than the
   injected evaluation instant.

Everything downstream -- `raw_events`, normalization, detection -- is already
written against the canonical envelope and is unaffected. That is the point of
having this seam at all.

## Determinism

`source_event_id` is derived from stable business identity (`crm:activity:<uuid>`),
not from a counter or a timestamp. Re-reading the same mirror produces the same
identifiers, which is what makes ingestion replay-safe at the database level:
`raw_events` is UNIQUE on `(source_system, source_event_id)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.domain.enums import EngagementEventType, EventType, SourceSystem

INGESTION_STATUS: Final = "SIMULATED"
"""Read by the capability catalog and stamped onto every ingestion summary. There is
no code path in v1 that sets this to anything else."""


@dataclass(frozen=True, slots=True)
class SourceEvent:
    """One payload as a source system would have delivered it."""

    source_system: SourceSystem
    source_event_id: str
    event_type: EventType
    occurred_at: datetime
    payload: JSONObject


def read_source_events(session: Session) -> tuple[SourceEvent, ...]:
    """Replay the seeded GTM mirror as source events.

    Ordered by `(source_system, source_event_id)` so a run produces a stable
    sequence -- the demo asserts on ordered output.
    """
    events: list[SourceEvent] = [
        *_opportunity_events(session),
        *_activity_events(session),
        *_usage_events(session),
        *_engagement_events(session),
        *_support_events(session),
    ]
    return tuple(
        sorted(events, key=lambda event: (event.source_system.value, event.source_event_id))
    )


def _opportunity_events(session: Session) -> list[SourceEvent]:
    rows = session.scalars(
        sa.select(orm.Opportunity).order_by(orm.Opportunity.opportunity_ref)
    ).all()
    out: list[SourceEvent] = []
    for row in rows:
        account = session.get(orm.Account, row.account_id)
        out.append(
            SourceEvent(
                source_system=SourceSystem.CRM,
                source_event_id=f"crm:opportunity:{row.opportunity_ref}",
                event_type=EventType.CRM_OPPORTUNITY_UPDATED,
                occurred_at=row.updated_at,
                payload={
                    "opportunity_ref": row.opportunity_ref,
                    "account_ref": account.account_ref if account else None,
                    "name": row.name,
                    "stage": row.stage.value,
                    "amount": str(row.amount),
                    "currency": row.currency,
                    "probability": str(row.probability),
                    "expected_close_date": row.expected_close_date.isoformat(),
                    "owner_id": row.owner_id,
                },
            )
        )
    return out


def _activity_events(session: Session) -> list[SourceEvent]:
    rows = session.scalars(sa.select(orm.Activity).order_by(orm.Activity.occurred_at)).all()
    out: list[SourceEvent] = []
    for row in rows:
        account = session.get(orm.Account, row.account_id)
        opportunity = (
            session.get(orm.Opportunity, row.opportunity_id)
            if row.opportunity_id is not None
            else None
        )
        out.append(
            SourceEvent(
                source_system=SourceSystem.CRM,
                source_event_id=f"crm:activity:{row.id}",
                event_type=EventType.CRM_ACTIVITY_LOGGED,
                occurred_at=row.occurred_at,
                payload={
                    "account_ref": account.account_ref if account else None,
                    "opportunity_ref": opportunity.opportunity_ref if opportunity else None,
                    "activity_type": row.activity_type.value,
                    "direction": row.direction.value,
                    "occurred_at": row.occurred_at.isoformat(),
                    # Untrusted free text. Carried verbatim into the envelope and
                    # never concatenated into a prompt (rule 14).
                    "subject": row.subject,
                    "body": row.body,
                },
            )
        )
    return out


def _usage_events(session: Session) -> list[SourceEvent]:
    rows = session.scalars(
        sa.select(orm.UsageSnapshot).order_by(orm.UsageSnapshot.period_start)
    ).all()
    out: list[SourceEvent] = []
    for row in rows:
        account = session.get(orm.Account, row.account_id)
        account_ref = account.account_ref if account else "unknown"
        out.append(
            SourceEvent(
                source_system=SourceSystem.PRODUCT,
                source_event_id=f"product:usage:{account_ref}:{row.period_start.isoformat()}",
                event_type=EventType.PRODUCT_USAGE_ROLLUP,
                # A weekly rollup is available at the end of its period.
                occurred_at=datetime.combine(
                    row.period_end, datetime.min.time(), tzinfo=row.created_at.tzinfo
                ),
                payload={
                    "account_ref": account_ref,
                    "period_start": row.period_start.isoformat(),
                    "period_end": row.period_end.isoformat(),
                    "active_users": row.active_users,
                    "sessions": row.sessions,
                    "feature_events": row.feature_events,
                    "usage_score": str(row.usage_score),
                },
            )
        )
    return out


def _engagement_events(session: Session) -> list[SourceEvent]:
    rows = session.scalars(
        sa.select(orm.EngagementEvent).order_by(orm.EngagementEvent.occurred_at)
    ).all()
    out: list[SourceEvent] = []
    for row in rows:
        account = session.get(orm.Account, row.account_id)
        event_type = (
            EventType.ENGAGEMENT_MEETING_HELD
            if row.event_type is EngagementEventType.MEETING_HELD
            else EventType.ENGAGEMENT_EMAIL_ACTIVITY
        )
        out.append(
            SourceEvent(
                source_system=SourceSystem.ENGAGEMENT,
                source_event_id=f"engagement:{row.id}",
                event_type=event_type,
                occurred_at=row.occurred_at,
                payload={
                    "account_ref": account.account_ref if account else None,
                    "channel": row.channel.value,
                    "event_type": row.event_type.value,
                    "occurred_at": row.occurred_at.isoformat(),
                },
            )
        )
    return out


def _support_events(session: Session) -> list[SourceEvent]:
    rows = session.scalars(
        sa.select(orm.SupportIssue).order_by(orm.SupportIssue.external_ref)
    ).all()
    out: list[SourceEvent] = []
    for row in rows:
        account = session.get(orm.Account, row.account_id)
        out.append(
            SourceEvent(
                source_system=SourceSystem.SUPPORT,
                source_event_id=f"support:issue:{row.external_ref}",
                event_type=EventType.SUPPORT_ISSUE_OPENED,
                occurred_at=row.opened_at,
                payload={
                    "account_ref": account.account_ref if account else None,
                    "external_ref": row.external_ref,
                    "severity": row.severity.value,
                    "status": row.status.value,
                    "opened_at": row.opened_at.isoformat(),
                    # Untrusted free text (rule 14).
                    "summary": row.summary,
                },
            )
        )
    return out
