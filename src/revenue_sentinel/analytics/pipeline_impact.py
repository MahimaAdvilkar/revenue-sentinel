"""The pipeline-impact calculation.

This is the number the product is judged on, so it is computed here -- in ordinary,
tested Python with `Decimal` arithmetic -- and never by a language model (rule 9).
`import-linter` contract R3 enforces that: `analytics/` cannot import
`intelligence/` or `agents/`, so the model cannot reach this code path even by
accident.

The golden scenario, worked in full:

    pipeline_value    = 180,000.00                       # opportunity amount
    weighted_value    = 180,000.00 x 0.60 = 108,000.00   # x stage probability
    stall_risk_factor = f(days_inactive=14, proposal) = 0.35
    at_risk_gross     = 108,000.00 x 0.35 =  37,800.00
    usage_offset      = g(usage_growth=0.40) = 0.15      # engagement reduces risk
    at_risk_value     =  37,800.00 x (1 - 0.15) = 32,130.00

Every intermediate is quantized to cents before it feeds the next step. That costs a
little precision and buys the property the dashboard promises: each line can be
checked by hand against `impact_assessments.inputs`, and the stored inputs reproduce
the stored outputs exactly.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from revenue_sentinel.analytics.risk_bands import (
    BANDS_VERSION,
    stall_risk_factor,
    usage_offset,
)
from revenue_sentinel.core.errors import CalculationError
from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.base import CurrencyCode, DomainModel, Money
from revenue_sentinel.domain.enums import OpportunityStage

IMPACT_METHOD_VERSION: Final = "pipeline_impact/v1"

CENTS: Final = Decimal("0.01")
_ONE: Final = Decimal("1")


def to_cents(value: Decimal) -> Decimal:
    """Round to two decimal places, half-up.

    Half-up rather than banker's rounding because these figures are read by people
    who will check them with a calculator, and a calculator rounds half-up.
    """
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


class PipelineImpact(DomainModel):
    """The result of one impact calculation, with its workings exposed.

    `at_risk_gross` is carried alongside `at_risk_value` so the effect of the usage
    offset is visible rather than folded silently into a single number.
    """

    method_version: str
    bands_version: str
    currency: CurrencyCode
    pipeline_value: Money
    weighted_value: Money
    at_risk_gross: Money
    at_risk_value: Money
    applied_stall_risk_factor: Decimal
    applied_usage_offset: Decimal
    inputs: JSONObject


def calculate_pipeline_impact(
    *,
    amount: Decimal,
    currency: str,
    probability: Decimal,
    days_inactive: int,
    stage: OpportunityStage,
    usage_growth: Decimal,
) -> PipelineImpact:
    """Compute weighted and at-risk pipeline value for a stalled opportunity.

    All arguments are keyword-only: this function takes six numbers of similar shape
    and a positional call site would be a silent correctness hazard.

    Raises:
        CalculationError: on a negative amount, an out-of-range probability, a
            negative inactivity window, or a closed opportunity stage. Bad inputs
            raise rather than returning a plausible-looking zero -- a wrong number
            on this screen is worse than a missing one.
    """
    if amount < 0:
        raise CalculationError(f"opportunity amount must be non-negative, got {amount}")
    if not (0 <= probability <= 1):
        raise CalculationError(f"probability must be within [0, 1], got {probability}")

    # Raises on a closed stage or a negative window; both are caller errors.
    stall_factor = stall_risk_factor(days_inactive=days_inactive, stage=stage)
    offset = usage_offset(usage_growth=usage_growth)

    pipeline_value = to_cents(amount)
    weighted_value = to_cents(pipeline_value * probability)
    at_risk_gross = to_cents(weighted_value * stall_factor)
    at_risk_value = to_cents(at_risk_gross * (_ONE - offset))

    inputs: JSONObject = {
        # Raw inputs, as decimal strings so the record is exact and JSON-safe.
        "amount": str(amount),
        "currency": currency,
        "probability": str(probability),
        "days_inactive": days_inactive,
        "stage": stage.value,
        "usage_growth": str(usage_growth),
        # Derived factors, so the bands do not have to be consulted to check the math.
        "stall_risk_factor": str(stall_factor),
        "usage_offset": str(offset),
        # Intermediates, in the order they are computed.
        "pipeline_value": str(pipeline_value),
        "weighted_value": str(weighted_value),
        "at_risk_gross": str(at_risk_gross),
        "at_risk_value": str(at_risk_value),
        # Versions, so a figure computed under different rules is identifiable.
        "method_version": IMPACT_METHOD_VERSION,
        "bands_version": BANDS_VERSION,
        "rounding": "ROUND_HALF_UP to 0.01 at every step",
    }

    return PipelineImpact(
        method_version=IMPACT_METHOD_VERSION,
        bands_version=BANDS_VERSION,
        currency=currency,
        pipeline_value=pipeline_value,
        weighted_value=weighted_value,
        at_risk_gross=at_risk_gross,
        at_risk_value=at_risk_value,
        applied_stall_risk_factor=stall_factor,
        applied_usage_offset=offset,
        inputs=inputs,
    )
