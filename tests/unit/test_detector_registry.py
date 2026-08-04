"""The detector registry.

The single most important assertion in this file is that **exactly one** detector is
implemented. A portfolio project is under constant quiet pressure to let "eight
detectors registered" become "eight detectors" in a README, and this is the check
that makes that impossible to do by accident.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from revenue_sentinel.core.config import Settings
from revenue_sentinel.domain.enums import IMPLEMENTED_SIGNAL_TYPES, SignalType
from revenue_sentinel.signals.detectors.roadmap import ROADMAP_DETECTORS, RoadmapDetector
from revenue_sentinel.signals.protocol import Detector
from revenue_sentinel.signals.registry import (
    all_detectors,
    build_registry,
    implemented_detectors,
)

VALID_URL = "postgresql+psycopg://sentinel:local@localhost:55432/revenue_sentinel"


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, database_url=VALID_URL)


def test_every_signal_type_has_a_registry_entry(settings: Settings) -> None:
    """A signal type with no detector would be a vocabulary the system cannot act on."""
    registry = build_registry(settings)
    assert set(registry) == set(SignalType)


def test_eight_detectors_are_registered(settings: Settings) -> None:
    assert len(all_detectors(settings)) == 8


def test_exactly_one_detector_is_implemented(settings: Settings) -> None:
    implemented = implemented_detectors(settings)

    assert len(implemented) == 1
    assert implemented[0].signal_type is SignalType.STALLED_OPPORTUNITY


def test_the_implemented_set_matches_the_domain_constant(settings: Settings) -> None:
    """`IMPLEMENTED_SIGNAL_TYPES` is what the capability matrix is written against."""
    from_registry = {detector.signal_type for detector in implemented_detectors(settings)}
    assert from_registry == set(IMPLEMENTED_SIGNAL_TYPES)


def test_seven_detectors_are_roadmap_contracts(settings: Settings) -> None:
    unimplemented = [d for d in all_detectors(settings) if not d.is_implemented]
    assert len(unimplemented) == 7


@pytest.mark.parametrize("contract", ROADMAP_DETECTORS, ids=lambda c: c.signal_type.value)
def test_a_roadmap_detector_raises_rather_than_returning_nothing(
    contract: RoadmapDetector,
) -> None:
    """Raising, not returning `None`.

    A contract that silently returned "no signal" would be indistinguishable from a
    working detector that found nothing -- and the difference is the whole point.
    """
    with pytest.raises(NotImplementedError, match="ROADMAP"):
        contract.evaluate(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("contract", ROADMAP_DETECTORS, ids=lambda c: c.signal_type.value)
def test_every_roadmap_contract_declares_real_metadata(contract: RoadmapDetector) -> None:
    """Declared but unbuilt still means describable: the dashboard's integration
    catalog renders these without pretending they work."""
    assert contract.version.endswith("/v0")
    assert contract.window > timedelta(0)
    assert contract.declared_params
    assert len(contract.rationale) > 20


def test_roadmap_contracts_cover_the_seven_documented_scenarios() -> None:
    expected = set(SignalType) - set(IMPLEMENTED_SIGNAL_TYPES)
    assert {contract.signal_type for contract in ROADMAP_DETECTORS} == expected


def test_all_detectors_satisfy_the_protocol(settings: Settings) -> None:
    for detector in all_detectors(settings):
        assert isinstance(detector, Detector)


def test_registry_order_is_stable(settings: Settings) -> None:
    """Ordered by signal type, so a run produces a deterministic sequence."""
    first = [d.signal_type for d in all_detectors(settings)]
    second = [d.signal_type for d in all_detectors(settings)]
    assert first == second == list(SignalType)


def test_thresholds_come_from_configuration(settings: Settings) -> None:
    from revenue_sentinel.signals.registry import build_stalled_opportunity_detector

    detector = build_stalled_opportunity_detector(settings)

    assert detector.params.inactivity_days == settings.detector_inactivity_days
    assert detector.params.min_amount_usd == settings.detector_min_amount_usd
    # Configured as a percentage, consumed as a ratio.
    assert detector.params.usage_growth * 100 == settings.detector_usage_growth_pct


def test_retuned_thresholds_reach_the_detector() -> None:
    """Changing configuration must change behaviour, or the knobs are decorative."""
    from revenue_sentinel.signals.registry import build_stalled_opportunity_detector

    retuned = Settings(
        _env_file=None,
        database_url=VALID_URL,
        detector_inactivity_days=30,
        detector_usage_growth_pct=10,
    )
    detector = build_stalled_opportunity_detector(retuned)

    assert detector.params.inactivity_days == 30
    assert detector.window == timedelta(days=30)
