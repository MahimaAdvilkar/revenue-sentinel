"""The money math.

These are the tests that matter most in Session 1. The figure this module computes
is the one shown on screen and spoken aloud in the demo, and rule 9 says it is
produced by tested code rather than by a model -- so the code had better be tested.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from revenue_sentinel.analytics.pipeline_impact import (
    IMPACT_METHOD_VERSION,
    calculate_pipeline_impact,
    to_cents,
)
from revenue_sentinel.analytics.risk_bands import (
    BANDS_VERSION,
    MAX_STALL_RISK,
    MAX_USAGE_OFFSET,
    stall_risk_factor,
    usage_offset,
)
from revenue_sentinel.core.errors import CalculationError
from revenue_sentinel.domain.enums import OpportunityStage


def golden() -> dict[str, object]:
    """The exact inputs from docs/demo-scenario.md §2."""
    return {
        "amount": Decimal("180000.00"),
        "currency": "USD",
        "probability": Decimal("0.60"),
        "days_inactive": 14,
        "stage": OpportunityStage.PROPOSAL,
        "usage_growth": Decimal("0.40"),
    }


# ---------------------------------------------------------------------------
# The golden scenario, to the cent
# ---------------------------------------------------------------------------
def test_golden_scenario_matches_the_documented_figures() -> None:
    result = calculate_pipeline_impact(**golden())  # type: ignore[arg-type]

    assert result.pipeline_value == Decimal("180000.00")
    assert result.weighted_value == Decimal("108000.00")
    assert result.at_risk_gross == Decimal("37800.00")
    assert result.at_risk_value == Decimal("32130.00")


def test_golden_scenario_applies_the_documented_factors() -> None:
    result = calculate_pipeline_impact(**golden())  # type: ignore[arg-type]

    assert result.applied_stall_risk_factor == Decimal("0.3500")
    assert result.applied_usage_offset == Decimal("0.1500")


def test_every_input_is_recorded_so_the_figure_can_be_recomputed_by_hand() -> None:
    result = calculate_pipeline_impact(**golden())  # type: ignore[arg-type]

    required = {
        "amount",
        "currency",
        "probability",
        "days_inactive",
        "stage",
        "usage_growth",
        "stall_risk_factor",
        "usage_offset",
        "pipeline_value",
        "weighted_value",
        "at_risk_gross",
        "at_risk_value",
        "method_version",
        "bands_version",
        "rounding",
    }
    assert required <= set(result.inputs)
    assert result.inputs["method_version"] == IMPACT_METHOD_VERSION
    assert result.inputs["bands_version"] == BANDS_VERSION


def test_stored_inputs_reproduce_the_stored_outputs() -> None:
    """The dashboard promises the figure is checkable by hand. Check it by hand."""
    result = calculate_pipeline_impact(**golden())  # type: ignore[arg-type]

    weighted = to_cents(Decimal(str(result.inputs["amount"])) * Decimal("0.60"))
    gross = to_cents(weighted * Decimal(str(result.inputs["stall_risk_factor"])))
    net = to_cents(gross * (Decimal("1") - Decimal(str(result.inputs["usage_offset"]))))

    assert weighted == result.weighted_value
    assert gross == result.at_risk_gross
    assert net == result.at_risk_value


# ---------------------------------------------------------------------------
# Types and rounding
# ---------------------------------------------------------------------------
def test_every_monetary_output_is_decimal_never_float() -> None:
    result = calculate_pipeline_impact(**golden())  # type: ignore[arg-type]

    for value in (
        result.pipeline_value,
        result.weighted_value,
        result.at_risk_gross,
        result.at_risk_value,
    ):
        assert isinstance(value, Decimal)
        assert not isinstance(value, float)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (Decimal("0.005"), Decimal("0.01")),  # half rounds up, not to even
        (Decimal("0.015"), Decimal("0.02")),  # banker's rounding would give 0.02
        (Decimal("0.025"), Decimal("0.03")),  # banker's rounding would give 0.02
        (Decimal("0.004"), Decimal("0.00")),
    ],
)
def test_rounding_is_half_up(raw: Decimal, expected: Decimal) -> None:
    assert to_cents(raw) == expected


def test_a_half_cent_weighted_value_rounds_up() -> None:
    result = calculate_pipeline_impact(
        amount=Decimal("100.01"),
        currency="USD",
        probability=Decimal("0.5"),
        days_inactive=14,
        stage=OpportunityStage.PROPOSAL,
        usage_growth=Decimal("0.40"),
    )
    # 100.01 x 0.5 = 50.005 -> 50.01 under ROUND_HALF_UP.
    assert result.weighted_value == Decimal("50.01")


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("days", [14, 21, 30, 45, 400])
@pytest.mark.parametrize(
    "stage",
    [OpportunityStage.DISCOVERY, OpportunityStage.PROPOSAL, OpportunityStage.NEGOTIATION],
)
def test_at_risk_never_exceeds_weighted_which_never_exceeds_pipeline(
    days: int, stage: OpportunityStage
) -> None:
    result = calculate_pipeline_impact(
        amount=Decimal("250000.00"),
        currency="USD",
        probability=Decimal("0.9"),
        days_inactive=days,
        stage=stage,
        usage_growth=Decimal("-0.5"),
    )
    assert result.at_risk_value <= result.at_risk_gross
    assert result.at_risk_gross <= result.weighted_value
    assert result.weighted_value <= result.pipeline_value


def test_zero_amount_produces_zeros_rather_than_an_error() -> None:
    """A genuinely zero opportunity is valid input, unlike a negative one."""
    result = calculate_pipeline_impact(
        amount=Decimal("0.00"),
        currency="USD",
        probability=Decimal("0.6"),
        days_inactive=14,
        stage=OpportunityStage.PROPOSAL,
        usage_growth=Decimal("0.40"),
    )
    assert result.pipeline_value == Decimal("0.00")
    assert result.weighted_value == Decimal("0.00")
    assert result.at_risk_value == Decimal("0.00")


def test_zero_probability_produces_zero_weighted_value() -> None:
    result = calculate_pipeline_impact(
        amount=Decimal("180000.00"),
        currency="USD",
        probability=Decimal("0"),
        days_inactive=14,
        stage=OpportunityStage.PROPOSAL,
        usage_growth=Decimal("0.40"),
    )
    assert result.weighted_value == Decimal("0.00")
    assert result.at_risk_value == Decimal("0.00")


# ---------------------------------------------------------------------------
# Guards -- bad input raises rather than returning a plausible zero
# ---------------------------------------------------------------------------
def test_negative_amount_raises() -> None:
    with pytest.raises(CalculationError, match="non-negative"):
        calculate_pipeline_impact(
            amount=Decimal("-1.00"),
            currency="USD",
            probability=Decimal("0.6"),
            days_inactive=14,
            stage=OpportunityStage.PROPOSAL,
            usage_growth=Decimal("0.40"),
        )


@pytest.mark.parametrize("bad", [Decimal("-0.01"), Decimal("1.01"), Decimal("2")])
def test_probability_outside_zero_to_one_raises(bad: Decimal) -> None:
    with pytest.raises(CalculationError, match=r"\[0, 1\]"):
        calculate_pipeline_impact(
            amount=Decimal("180000.00"),
            currency="USD",
            probability=bad,
            days_inactive=14,
            stage=OpportunityStage.PROPOSAL,
            usage_growth=Decimal("0.40"),
        )


def test_negative_inactivity_window_raises() -> None:
    with pytest.raises(CalculationError, match="days_inactive"):
        calculate_pipeline_impact(
            amount=Decimal("180000.00"),
            currency="USD",
            probability=Decimal("0.6"),
            days_inactive=-1,
            stage=OpportunityStage.PROPOSAL,
            usage_growth=Decimal("0.40"),
        )


@pytest.mark.parametrize("closed", [OpportunityStage.CLOSED_WON, OpportunityStage.CLOSED_LOST])
def test_closed_stage_raises_rather_than_returning_a_number(closed: OpportunityStage) -> None:
    """Stall risk on a closed deal is a meaningless question, not a small number."""
    with pytest.raises(CalculationError, match="closed stage"):
        calculate_pipeline_impact(
            amount=Decimal("180000.00"),
            currency="USD",
            probability=Decimal("0.6"),
            days_inactive=14,
            stage=closed,
            usage_growth=Decimal("0.40"),
        )


# ---------------------------------------------------------------------------
# Band boundaries -- the values most likely to be quietly wrong
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (0, Decimal("0.0000")),
        (13, Decimal("0.0000")),  # below the detection threshold: not stalled
        (14, Decimal("0.3500")),  # the documented golden value
        (20, Decimal("0.3500")),
        (21, Decimal("0.4500")),
        (29, Decimal("0.4500")),
        (30, Decimal("0.5500")),
        (44, Decimal("0.5500")),
        (45, Decimal("0.6500")),
        (365, Decimal("0.6500")),
    ],
)
def test_stall_risk_band_boundaries_for_proposal(days: int, expected: Decimal) -> None:
    assert stall_risk_factor(days_inactive=days, stage=OpportunityStage.PROPOSAL) == expected


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        (OpportunityStage.DISCOVERY, Decimal("0.2800")),  # 0.35 x 0.80
        (OpportunityStage.PROPOSAL, Decimal("0.3500")),  # 0.35 x 1.00
        (OpportunityStage.NEGOTIATION, Decimal("0.4200")),  # 0.35 x 1.20
    ],
)
def test_stage_multiplier_applies(stage: OpportunityStage, expected: Decimal) -> None:
    assert stall_risk_factor(days_inactive=14, stage=stage) == expected


def test_stall_risk_is_capped() -> None:
    """Negotiation at 45+ days would exceed the cap without it: 0.65 x 1.20 = 0.78."""
    factor = stall_risk_factor(days_inactive=500, stage=OpportunityStage.NEGOTIATION)
    assert factor <= MAX_STALL_RISK
    assert factor == Decimal("0.7800")


@pytest.mark.parametrize(
    ("growth", "expected"),
    [
        (Decimal("-0.50"), Decimal("0.0000")),  # declining usage earns nothing
        (Decimal("-0.01"), Decimal("0.0000")),
        (Decimal("0.00"), Decimal("0.0500")),
        (Decimal("0.19"), Decimal("0.0500")),
        (Decimal("0.20"), Decimal("0.1000")),
        (Decimal("0.39"), Decimal("0.1000")),  # one point below the golden band
        (Decimal("0.40"), Decimal("0.1500")),  # the documented golden value
        (Decimal("0.79"), Decimal("0.1500")),
        (Decimal("0.80"), Decimal("0.2000")),
        (Decimal("5.00"), Decimal("0.2000")),
    ],
)
def test_usage_offset_band_boundaries(growth: Decimal, expected: Decimal) -> None:
    assert usage_offset(usage_growth=growth) == expected


def test_usage_offset_is_capped() -> None:
    assert usage_offset(usage_growth=Decimal("100")) == MAX_USAGE_OFFSET.quantize(Decimal("0.0001"))


def test_declining_usage_gives_no_relief_on_the_at_risk_figure() -> None:
    """Rising usage reduces risk; falling usage must not."""
    falling = calculate_pipeline_impact(
        amount=Decimal("180000.00"),
        currency="USD",
        probability=Decimal("0.60"),
        days_inactive=14,
        stage=OpportunityStage.PROPOSAL,
        usage_growth=Decimal("-0.20"),
    )
    assert falling.applied_usage_offset == Decimal("0.0000")
    assert falling.at_risk_value == falling.at_risk_gross == Decimal("37800.00")
