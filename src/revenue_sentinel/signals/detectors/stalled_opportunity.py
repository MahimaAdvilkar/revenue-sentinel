"""`stalled_opportunity` -- the only detector implemented in v1.

Fires when a high-value opportunity has gone quiet on the sales side **while**
product usage from the account is climbing. The conjunction is the whole point:
either half alone is unremarkable, and together they are the sharpest pattern in
GTM -- the buyer is engaged and the seller is absent.

| Condition | Threshold | Why |
|---|---|---|
| Stage is open | discovery / proposal / negotiation | A closed deal cannot stall |
| Amount at or above the floor | >= $100,000 | "High-value" |
| Sales silence | >= 14 days | Two weeks without contact after a proposal |
| Usage growth | >= 40% week over week | Active evaluation, not noise |

Pure: `evaluated_at` arrives in the context, and the detector holds no session.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Final

from revenue_sentinel.analytics.windows import days_since_last_sales_touch, week_over_week_growth
from revenue_sentinel.core.errors import CalculationError
from revenue_sentinel.domain.enums import OPEN_STAGES, OpportunityStage, SignalType
from revenue_sentinel.domain.signals import SignalCandidate
from revenue_sentinel.incidents.severity import severity_for_weighted_value
from revenue_sentinel.signals.protocol import DetectionContext

DETECTOR_VERSION: Final = "stalled_opportunity/v1"

SUPPORTED_CURRENCY: Final = "USD"
"""v1 compares against a USD floor and holds no exchange rates. An opportunity in
another currency does not fire -- converting at an unstated rate would be a
fabricated number in the one place this system promises not to fabricate."""


@dataclass(frozen=True, slots=True)
class StalledOpportunityParams:
    """Thresholds, injected rather than read from configuration inside the detector.

    Keeping these as data is what lets the boundary tests drive 13 days versus 14
    without touching the environment.
    """

    min_amount_usd: Decimal
    inactivity_days: int
    usage_growth: Decimal
    open_stages: frozenset[OpportunityStage] = frozenset(OPEN_STAGES)


@dataclass(frozen=True, slots=True)
class StalledOpportunityDetector:
    """The v1 detector. Frozen: its thresholds cannot drift mid-run."""

    params: StalledOpportunityParams

    @property
    def signal_type(self) -> SignalType:
        return SignalType.STALLED_OPPORTUNITY

    @property
    def version(self) -> str:
        return DETECTOR_VERSION

    @property
    def window(self) -> timedelta:
        return timedelta(days=self.params.inactivity_days)

    @property
    def is_implemented(self) -> bool:
        return True

    def evaluate(self, context: DetectionContext) -> SignalCandidate | None:
        opportunity = context.opportunity

        if opportunity.stage not in self.params.open_stages:
            return None
        if opportunity.currency != SUPPORTED_CURRENCY:
            return None
        if opportunity.amount < self.params.min_amount_usd:
            return None

        days_inactive = days_since_last_sales_touch(
            latest_sales_touch=context.latest_sales_touch,
            evaluated_at=context.evaluated_at,
        )
        # `None` means no sales touch was ever logged. Treated as "does not fire":
        # absent history is not evidence of a stall. See analytics/windows.py.
        if days_inactive is None or days_inactive < self.params.inactivity_days:
            return None

        growth = self._usage_growth(context)
        if growth is None or growth < self.params.usage_growth:
            return None

        return SignalCandidate(
            signal_type=self.signal_type,
            detector_version=self.version,
            severity=severity_for_weighted_value(
                amount=opportunity.amount, probability=opportunity.probability
            ),
            account_id=context.account.id,
            opportunity_id=opportunity.id,
            detected_at=context.evaluated_at,
            dedupe_key=self.dedupe_key(context),
            evidence_refs=self._evidence_refs(context),
        )

    def _usage_growth(self, context: DetectionContext) -> Decimal | None:
        """Week-over-week growth across the two most recent snapshots.

        Returns `None` when growth is not computable -- fewer than two snapshots,
        or a zero baseline. Both are "not enough evidence", not "no growth".
        """
        if len(context.usage_window) < 2:
            return None

        earlier, later = context.usage_window[-2], context.usage_window[-1]
        try:
            return week_over_week_growth(earlier=earlier.feature_events, later=later.feature_events)
        except CalculationError:
            return None

    def dedupe_key(self, context: DetectionContext) -> str:
        """`sha256(signal_type | opportunity_ref | detector_version | window_start)`.

        `window_start` is truncated to the UTC **date**. Without truncation two runs
        seconds apart produce different keys and therefore duplicate signals, so the
        replay-safety guarantee would hold under a frozen clock and quietly fail
        under a real one.

        `detector_version` is part of the key on purpose: retuning a detector may
        legitimately re-report a condition an earlier version already flagged. That
        is a different claim, not a duplicate.
        """
        window_start = (context.evaluated_at - self.window).date().isoformat()
        material = "|".join(
            (
                self.signal_type.value,
                context.opportunity.opportunity_ref,
                self.version,
                window_start,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _evidence_refs(self, context: DetectionContext) -> tuple[str, ...]:
        """Normalized events that evidence this condition.

        Ties the signal back to the events it was derived from, so "why did this
        fire?" is answerable from stored data rather than by re-running detection.
        """
        relevant = {
            "crm.activity.logged",
            "product.usage.rollup",
            "crm.opportunity.updated",
        }
        return tuple(
            sorted(str(event.id) for event in context.events if event.event_type.value in relevant)
        )
