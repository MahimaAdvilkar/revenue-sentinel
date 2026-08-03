"""The two risk functions behind the impact calculation, as explicit banded tables.

`docs/demo-scenario.md` asserts `f(days_inactive=14, stage=Proposal) = 0.35` and
`f(usage_growth=0.40) = +0.15` but does not define `f`. This module is that
definition. See ADR-0008 for why it is a step table rather than a fitted curve.

**These are heuristics, and the claim made for them is narrow.** They are not
empirically calibrated against historical win rates -- no such dataset exists for a
synthetic account. What they are is *deterministic, versioned, inspectable, and
tested at every boundary*, which is the property the system actually depends on: the
same inputs produce the same figure on every run, and a human can check the
arithmetic by reading a table.

Bands rather than a continuous function because a step table can be read and
argued with by a revenue leader. A fitted curve would look more rigorous and be less
defensible, since its coefficients would have been chosen to hit the demo numbers.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from revenue_sentinel.core.errors import CalculationError
from revenue_sentinel.domain.enums import OPEN_STAGES, OpportunityStage

BANDS_VERSION: Final = "risk_bands/v1"

_FACTOR_PRECISION: Final = Decimal("0.0001")
"""Both factors are reported at four decimal places so that `impact_assessments.inputs`
reads consistently -- a stage multiplier would otherwise leave one factor at two
decimals and the other at four."""

# ---------------------------------------------------------------------------
# Stall risk
# ---------------------------------------------------------------------------
# Read as: at or beyond `min_days` of sales silence, this share of the weighted
# value is considered at risk, before any usage offset.
#
# The first band is 0.00 by construction: below the 14-day detection threshold a
# deal is not stalled, so a caller asking for its stall risk should get nothing,
# not a small positive number that looks like evidence.
_STALL_RISK_BY_INACTIVITY: Final[tuple[tuple[int, Decimal], ...]] = (
    (0, Decimal("0.00")),
    (14, Decimal("0.35")),
    (21, Decimal("0.45")),
    (30, Decimal("0.55")),
    (45, Decimal("0.65")),
)

# Later stages lose more to silence: the buyer has alternatives in play and the
# momentum that carried the deal into the stage is what decays.
_STAGE_MULTIPLIER: Final[dict[OpportunityStage, Decimal]] = {
    OpportunityStage.DISCOVERY: Decimal("0.80"),
    OpportunityStage.PROPOSAL: Decimal("1.00"),
    OpportunityStage.NEGOTIATION: Decimal("1.20"),
}

MAX_STALL_RISK: Final = Decimal("0.85")
"""No deal is ever treated as more than 85% lost from inactivity alone. A factor of
1.00 would assert the deal is already dead, which silence alone does not establish."""


# ---------------------------------------------------------------------------
# Usage offset
# ---------------------------------------------------------------------------
# Rising product usage is evidence the buyer is still engaged, so it *reduces* the
# at-risk figure. Declining usage earns no offset -- it is not reassuring, and
# treating it as mildly reassuring would be the wrong direction.
_USAGE_OFFSET_BY_GROWTH: Final[tuple[tuple[Decimal, Decimal], ...]] = (
    (Decimal("-1.00"), Decimal("0.00")),
    (Decimal("0.00"), Decimal("0.05")),
    (Decimal("0.20"), Decimal("0.10")),
    (Decimal("0.40"), Decimal("0.15")),
    (Decimal("0.80"), Decimal("0.20")),
)

MAX_USAGE_OFFSET: Final = Decimal("0.20")
"""Usage growth can reduce the at-risk figure by at most 20%. Engagement is a
signal, not an all-clear: a buyer can use a product enthusiastically and still buy
from someone else."""


def stall_risk_factor(*, days_inactive: int, stage: OpportunityStage) -> Decimal:
    """Share of weighted value at risk from sales inactivity, in [0, 0.85].

    Raises `CalculationError` on a closed stage: stall risk on a closed opportunity
    is not a small number, it is a meaningless question.
    """
    if days_inactive < 0:
        raise CalculationError(f"days_inactive must be non-negative, got {days_inactive}")
    if stage not in OPEN_STAGES:
        raise CalculationError(f"stall risk is undefined for closed stage {stage}")

    base = _STALL_RISK_BY_INACTIVITY[0][1]
    for min_days, band_factor in _STALL_RISK_BY_INACTIVITY:
        if days_inactive >= min_days:
            base = band_factor
        else:
            break

    return min(base * _STAGE_MULTIPLIER[stage], MAX_STALL_RISK).quantize(_FACTOR_PRECISION)


def usage_offset(*, usage_growth: Decimal) -> Decimal:
    """Reduction applied to the at-risk figure for engagement, in [0, 0.20].

    `usage_growth` is a ratio, not a percentage: 0.40 means +40%.
    """
    offset = _USAGE_OFFSET_BY_GROWTH[0][1]
    for min_growth, value in _USAGE_OFFSET_BY_GROWTH:
        if usage_growth >= min_growth:
            offset = value
        else:
            break

    return min(offset, MAX_USAGE_OFFSET).quantize(_FACTOR_PRECISION)
