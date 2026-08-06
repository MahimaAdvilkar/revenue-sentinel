"""Product-usage adapter -- **SIMULATED**.

Reads the locally seeded `usage_snapshots` mirror. No external system is contacted.

## What changes when this becomes real

**API.** A warehouse query (Snowflake / BigQuery) against an events table, or Segment
Profiles API. Most likely a scheduled rollup job we own rather than a live API, because
per-request aggregation over raw events is too slow to sit in an agent's critical path.

**Auth.** Warehouse: a service account with a read-only role scoped to one schema, key
rotated by the platform team. Segment: a workspace token. Neither is an API key in an
env var; both need a secret manager.

**Rate limits.** Warehouses meter by compute, not requests -- the limit is cost, not
`429`. A tight loop here is expensive rather than throttled, which is a worse failure
mode because nothing stops it. Caching the weekly rollup becomes mandatory.

**Pagination.** Not applicable to a rollup, but the underlying event scan needs
partition pruning on `occurred_at` or it degrades from seconds to minutes as history
grows.

**Fields that differ.** `feature_events` becomes a sum over a raw event stream whose
definition of "feature" is a product decision, not a database one -- the single most
likely place for this metric to quietly stop meaning what the detector assumes.
`active_users` needs a deduplication window (daily? weekly?) that our seed sidesteps.
Late-arriving events mean a period's numbers change after it closes, so `usage_score`
must record when it was computed.
"""

from __future__ import annotations

from datetime import date
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.analytics.windows import week_over_week_growth
from revenue_sentinel.core.errors import CalculationError
from revenue_sentinel.core.types import JSONObject, JSONValue
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.integrations.simulated.behaviour import SimulatedBehaviour
from revenue_sentinel.integrations.status import SIMULATED

INTEGRATION_STATUS: Final = SIMULATED


class SimulatedProductAdapter:
    """Fixture-backed product usage."""

    def __init__(self, session: Session, behaviour: SimulatedBehaviour) -> None:
        self._session = session
        self._behaviour = behaviour

    def get_usage_summary(
        self, *, account_ref: str, period_start: date, period_end: date
    ) -> JSONObject:
        self._behaviour.before_call("product_get_usage_summary")
        account = self._session.scalar(
            sa.select(orm.Account).where(orm.Account.account_ref == account_ref)
        )
        if account is None:
            return {}

        rows = self._session.scalars(
            sa.select(orm.UsageSnapshot)
            .where(
                orm.UsageSnapshot.account_id == account.id,
                orm.UsageSnapshot.period_start >= period_start,
                orm.UsageSnapshot.period_end <= period_end,
            )
            .order_by(orm.UsageSnapshot.period_start)
        ).all()

        periods: list[JSONValue] = []
        for index, row in enumerate(rows):
            growth: str | None = None
            if index > 0:
                try:
                    growth = str(
                        week_over_week_growth(
                            earlier=rows[index - 1].feature_events,
                            later=row.feature_events,
                        )
                    )
                except CalculationError:
                    growth = None
            periods.append(
                {
                    "period_start": row.period_start.isoformat(),
                    "period_end": row.period_end.isoformat(),
                    "active_users": row.active_users,
                    "sessions": row.sessions,
                    "feature_events": row.feature_events,
                    "usage_score": str(row.usage_score),
                    "week_over_week_growth": growth,
                }
            )

        return {"account_ref": account_ref, "period_count": len(periods), "periods": periods}
