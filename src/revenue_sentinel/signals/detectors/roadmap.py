"""The seven detectors that are contracts, not implementations.

Each declares its `signal_type`, `version`, `window`, and the parameters it would
need. None of them has a body: `evaluate()` raises.

This is deliberate rather than lazy. `docs/event-model.md` §4 lists seven further
scenarios, and the temptation in a portfolio project is to stub them so the count
looks impressive. Raising `NotImplementedError` means the registry can hold eight
detectors while `is_implemented` reports exactly one -- a fact the capability
matrix reads and a test asserts, so "eight detectors" cannot be claimed anywhere,
including by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.enums import SignalType
from revenue_sentinel.domain.signals import SignalCandidate
from revenue_sentinel.signals.protocol import DetectionContext


@dataclass(frozen=True, slots=True)
class RoadmapDetector:
    """A declared-but-unbuilt detector.

    Holds real metadata so the registry, the dashboard's integration catalog, and
    the capability matrix can describe it accurately without pretending it works.
    """

    signal_type: SignalType
    version: str
    window: timedelta
    declared_params: JSONObject
    rationale: str

    @property
    def is_implemented(self) -> bool:
        return False

    def evaluate(self, context: DetectionContext) -> SignalCandidate | None:
        raise NotImplementedError(
            f"{self.signal_type.value} is a registered contract with no implementation. "
            f"Status: ROADMAP. See docs/event-model.md §4."
        )


ROADMAP_DETECTORS: Final[tuple[RoadmapDetector, ...]] = (
    RoadmapDetector(
        signal_type=SignalType.RENEWAL_RISK,
        version="renewal_risk/v0",
        window=timedelta(days=90),
        declared_params={
            "days_to_renewal": 90,
            "usage_decline_pct": 25,
            "min_arr_usd": 50000,
        },
        rationale="Declining usage inside the renewal window on a material contract.",
    ),
    RoadmapDetector(
        signal_type=SignalType.DEAL_SLIPPAGE,
        version="deal_slippage/v0",
        window=timedelta(days=30),
        declared_params={"close_date_pushes": 2, "lookback_days": 60},
        rationale="An expected close date moved more than once in a quarter.",
    ),
    RoadmapDetector(
        signal_type=SignalType.PQA_DISCOVERY,
        version="pqa_discovery/v0",
        window=timedelta(days=14),
        declared_params={
            "min_active_users": 10,
            "usage_growth_pct": 50,
            "has_open_opportunity": False,
        },
        rationale="A free or trial account using the product like a customer, with no deal open.",
    ),
    RoadmapDetector(
        signal_type=SignalType.ACCOUNT_EXPANSION,
        version="account_expansion/v0",
        window=timedelta(days=30),
        declared_params={"seat_utilisation_pct": 90, "feature_breadth": 5},
        rationale="Seat or feature usage approaching the limits of the current contract.",
    ),
    RoadmapDetector(
        signal_type=SignalType.CRM_DATA_QUALITY,
        version="crm_data_quality/v0",
        window=timedelta(days=1),
        declared_params={"required_fields": ["amount", "stage", "expected_close_date"]},
        rationale="Material opportunities missing fields the forecast depends on.",
    ),
    RoadmapDetector(
        signal_type=SignalType.ENRICHMENT_COST_ANOMALY,
        version="enrichment_cost_anomaly/v0",
        window=timedelta(days=30),
        declared_params={"spend_increase_pct": 40, "baseline_months": 3},
        rationale="Enrichment provider spend rising without a matching rise in matched records.",
    ),
    RoadmapDetector(
        signal_type=SignalType.CAMPAIGN_UNDERPERFORMANCE,
        version="campaign_underperformance/v0",
        window=timedelta(days=30),
        declared_params={"pipeline_target_pct": 60, "min_spend_usd": 10000},
        rationale="Campaign spend materially ahead of the pipeline it generated.",
    ),
)
