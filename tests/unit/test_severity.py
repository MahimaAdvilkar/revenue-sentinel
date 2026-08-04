"""Incident severity bands (ADR-0011).

`docs/demo-scenario.md` asserts `INC-001` is `HIGH` without defining severity
anywhere. These tests pin the definition that now exists, and both sides of every
band boundary.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from revenue_sentinel.core.errors import CalculationError
from revenue_sentinel.domain.enums import Severity
from revenue_sentinel.incidents.severity import (
    SEVERITY_BANDS_VERSION,
    severity_for_weighted_value,
)


def test_the_golden_scenario_is_high() -> None:
    """180,000.00 x 0.60 = 108,000.00 -> HIGH, which is what the demo doc claims."""
    assert (
        severity_for_weighted_value(amount=Decimal("180000.00"), probability=Decimal("0.6000"))
        is Severity.HIGH
    )


@pytest.mark.parametrize(
    ("weighted", "expected"),
    [
        (Decimal("0.00"), Severity.LOW),
        (Decimal("24999.99"), Severity.LOW),
        (Decimal("25000.00"), Severity.MEDIUM),
        (Decimal("99999.99"), Severity.MEDIUM),
        (Decimal("100000.00"), Severity.HIGH),
        (Decimal("249999.99"), Severity.HIGH),
        (Decimal("250000.00"), Severity.CRITICAL),
        (Decimal("9000000.00"), Severity.CRITICAL),
    ],
)
def test_every_band_boundary(weighted: Decimal, expected: Severity) -> None:
    """Driven at probability 1.0 so `weighted` is the amount, exactly."""
    assert severity_for_weighted_value(amount=weighted, probability=Decimal("1")) is expected


def test_probability_actually_weights_the_amount() -> None:
    """A large deal at low probability is not a critical incident."""
    assert (
        severity_for_weighted_value(amount=Decimal("500000.00"), probability=Decimal("0.05"))
        is Severity.MEDIUM
    )


def test_zero_probability_is_low_regardless_of_amount() -> None:
    assert (
        severity_for_weighted_value(amount=Decimal("9000000.00"), probability=Decimal("0"))
        is Severity.LOW
    )


def test_rounding_matches_the_impact_calculator() -> None:
    """Severity and the impact assessment must agree about the weighted figure.

    24,999.995 rounds half-up to 25,000.00 in both places, so this lands in MEDIUM.
    """
    assert (
        severity_for_weighted_value(amount=Decimal("49999.99"), probability=Decimal("0.5"))
        is Severity.MEDIUM
    )


def test_negative_amount_raises() -> None:
    with pytest.raises(CalculationError, match="non-negative"):
        severity_for_weighted_value(amount=Decimal("-1.00"), probability=Decimal("0.5"))


@pytest.mark.parametrize("bad", [Decimal("-0.01"), Decimal("1.01")])
def test_probability_out_of_range_raises(bad: Decimal) -> None:
    with pytest.raises(CalculationError, match=r"\[0, 1\]"):
        severity_for_weighted_value(amount=Decimal("100000.00"), probability=bad)


def test_bands_are_versioned() -> None:
    """A figure computed under different rules must stay identifiable."""
    assert SEVERITY_BANDS_VERSION == "severity_bands/v1"
