"""The detector registry.

Eight detectors are registered. **One of them works.** `implemented_detectors()` is
the only accessor the dispatcher uses, so a ROADMAP contract cannot be run by
accident -- it would have to be reached through `all_detectors()`, which exists for
the capability catalog and for tests.
"""

from __future__ import annotations

from decimal import Decimal

from revenue_sentinel.core.config import Settings
from revenue_sentinel.core.errors import ConfigurationError
from revenue_sentinel.domain.enums import SignalType
from revenue_sentinel.signals.detectors.roadmap import ROADMAP_DETECTORS
from revenue_sentinel.signals.detectors.stalled_opportunity import (
    StalledOpportunityDetector,
    StalledOpportunityParams,
)
from revenue_sentinel.signals.protocol import Detector


def build_stalled_opportunity_detector(settings: Settings) -> StalledOpportunityDetector:
    """Construct the v1 detector from configuration.

    Thresholds are read here, once, and handed to the detector as data. The
    detector never touches `Settings`, which is what keeps it pure.
    """
    return StalledOpportunityDetector(
        params=StalledOpportunityParams(
            min_amount_usd=settings.detector_min_amount_usd,
            inactivity_days=settings.detector_inactivity_days,
            usage_growth=Decimal(settings.detector_usage_growth_pct) / Decimal(100),
        )
    )


def build_registry(settings: Settings) -> dict[SignalType, Detector]:
    """Every registered detector, implemented and ROADMAP alike."""
    registry: dict[SignalType, Detector] = {
        SignalType.STALLED_OPPORTUNITY: build_stalled_opportunity_detector(settings)
    }

    for contract in ROADMAP_DETECTORS:
        if contract.signal_type in registry:
            raise ConfigurationError(f"duplicate detector registration: {contract.signal_type}")
        registry[contract.signal_type] = contract

    missing = set(SignalType) - set(registry)
    if missing:
        raise ConfigurationError(
            f"signal types with no registry entry: {sorted(t.value for t in missing)}"
        )
    return registry


def all_detectors(settings: Settings) -> tuple[Detector, ...]:
    """All eight, ordered by signal type. For the capability catalog and tests."""
    registry = build_registry(settings)
    return tuple(registry[signal_type] for signal_type in SignalType)


def implemented_detectors(settings: Settings) -> tuple[Detector, ...]:
    """Only detectors with a real implementation. The dispatcher uses this."""
    return tuple(detector for detector in all_detectors(settings) if detector.is_implemented)
