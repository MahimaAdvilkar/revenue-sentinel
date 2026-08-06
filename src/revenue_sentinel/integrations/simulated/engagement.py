"""Engagement adapter -- **SIMULATED**.

Reads the locally seeded `engagement_events` mirror. No mailbox is opened.

## What changes when this becomes real

**API.** Gmail API (`users.messages.list`, `users.history.list`) or Microsoft Graph
(`/me/messages`), plus Google Calendar `events.list` or Graph `/me/events` for
meetings. Opens and clicks are **not** available from a mailbox at all -- they come
from a sequencing tool (Outreach, Salesloft) or tracking pixels, which is a third
integration this port currently pretends is one.

**Auth.** OAuth 2.0 with per-user consent and domain-wide delegation for a workspace.
This is the most sensitive integration in the system: the scope needed to read
engagement is the scope needed to read every email the rep has. `gmail.readonly` and
`gmail.compose` must be requested separately, and an admin will ask why.

**Rate limits.** Gmail: 250 quota units/user/second, list ≈ 5 units. Graph: throttled
per-app with `Retry-After`. Both fail in bursts, which is what makes `RATE_LIMITED`
worth modelling.

**Pagination.** Both cursor-paginate and cap page size at 100-500. A busy mailbox needs
incremental sync via `historyId` / delta tokens rather than re-listing.

**Fields that differ.** `opened` and `clicked` do not exist in a mailbox -- they are
tracking-tool concepts and are unreliable (image proxies inflate opens; corporate
scanners fabricate clicks). Treating them as truth is a product risk this fixture
hides. Meeting "held" versus "scheduled" needs the attendee response status, and a
declined-but-not-deleted event still appears.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.domain.enums import EngagementEventType
from revenue_sentinel.integrations.simulated.behaviour import SimulatedBehaviour
from revenue_sentinel.integrations.status import SIMULATED

INTEGRATION_STATUS: Final = SIMULATED


class SimulatedEngagementAdapter:
    """Fixture-backed engagement."""

    def __init__(self, session: Session, behaviour: SimulatedBehaviour) -> None:
        self._session = session
        self._behaviour = behaviour

    def get_email_activity(self, *, account_ref: str, since: datetime) -> JSONObject:
        self._behaviour.before_call("engagement_get_email_activity")
        return self._activity(
            account_ref=account_ref,
            since=since,
            include={
                EngagementEventType.SENT,
                EngagementEventType.OPENED,
                EngagementEventType.CLICKED,
            },
        )

    def get_meeting_activity(self, *, account_ref: str, since: datetime) -> JSONObject:
        self._behaviour.before_call("engagement_get_meeting_activity")
        return self._activity(
            account_ref=account_ref, since=since, include={EngagementEventType.MEETING_HELD}
        )

    def _activity(
        self, *, account_ref: str, since: datetime, include: set[EngagementEventType]
    ) -> JSONObject:
        account = self._session.scalar(
            sa.select(orm.Account).where(orm.Account.account_ref == account_ref)
        )
        if account is None:
            return {}
        rows = self._session.scalars(
            sa.select(orm.EngagementEvent)
            .where(
                orm.EngagementEvent.account_id == account.id,
                orm.EngagementEvent.occurred_at >= since,
                orm.EngagementEvent.event_type.in_(list(include)),
            )
            .order_by(orm.EngagementEvent.occurred_at)
        ).all()

        counts: dict[str, int] = {}
        for row in rows:
            counts[row.event_type.value] = counts.get(row.event_type.value, 0) + 1

        return {
            "account_ref": account_ref,
            "count": len(rows),
            "totals_by_event_type": dict(sorted(counts.items())),
            "events": [
                {
                    "channel": row.channel.value,
                    "event_type": row.event_type.value,
                    "occurred_at": row.occurred_at.isoformat(),
                }
                for row in rows
            ],
        }
