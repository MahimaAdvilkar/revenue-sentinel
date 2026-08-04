"""Incident severity, as banded weighted pipeline value.

`docs/demo-scenario.md` asserts that `INC-001` is `HIGH` without saying why, and no
authoritative document defined severity anywhere. This module is that definition.
See ADR-0011.

| Weighted value (`amount x probability`) | Severity |
|---|---|
| >= $250,000 | `CRITICAL` |
| >= $100,000 | `HIGH` |
| >= $25,000 | `MEDIUM` |
| < $25,000 | `LOW` |

Golden scenario: 180,000.00 x 0.60 = 108,000.00 -> **HIGH**, which is what the demo
document claims.

**The claim made for these bands is narrow**, exactly as in ADR-0008: they are
deterministic, versioned, and boundary-tested, not empirically calibrated. Severity
here means "how much weighted pipeline is in play", which is a defensible proxy for
attention and nothing more. It deliberately does not fold in stage, account tier, or
how long the condition has persisted -- each would be another uncalibrated weight,
and a composite of four guesses is not more rigorous than one.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from revenue_sentinel.analytics.pipeline_impact import to_cents
from revenue_sentinel.core.errors import CalculationError
from revenue_sentinel.domain.enums import Severity

SEVERITY_BANDS_VERSION: Final = "severity_bands/v1"

# Ordered high to low; the first band the value clears wins.
_BANDS: Final[tuple[tuple[Decimal, Severity], ...]] = (
    (Decimal("250000.00"), Severity.CRITICAL),
    (Decimal("100000.00"), Severity.HIGH),
    (Decimal("25000.00"), Severity.MEDIUM),
)


def severity_for_weighted_value(*, amount: Decimal, probability: Decimal) -> Severity:
    """Classify an opportunity by weighted pipeline value.

    Reuses the same `amount x probability` arithmetic and cent-rounding as
    [`pipeline_impact.py`](../analytics/pipeline_impact.py), so an incident's
    severity and its impact assessment can never disagree about the weighted figure
    they are both derived from.
    """
    if amount < 0:
        raise CalculationError(f"amount must be non-negative, got {amount}")
    if not (0 <= probability <= 1):
        raise CalculationError(f"probability must be within [0, 1], got {probability}")

    weighted = to_cents(amount * probability)
    for floor, severity in _BANDS:
        if weighted >= floor:
            return severity
    return Severity.LOW
