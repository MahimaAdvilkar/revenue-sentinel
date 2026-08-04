"""The two window calculations detection and impact assessment share.

Both live here rather than inside the detector because
[`pipeline_impact.py`](pipeline_impact.py) consumes the same two numbers:
`days_inactive` selects the stall-risk band, and `usage_growth` selects the usage
offset. One definition, tested once, used by both — a second copy inside
`signals/` would be the kind of drift that makes a detector and a dollar figure
quietly disagree about the same opportunity.

Both functions are pure. Evaluation time is passed in, never read (rule 9 and
`docs/event-model.md` §4).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final

from revenue_sentinel.core.errors import CalculationError

GROWTH_PRECISION: Final = Decimal("0.0001")
"""Growth is reported at four decimal places, matching the risk-band factors so
`impact_assessments.inputs` reads consistently."""


def days_since_last_sales_touch(
    *, latest_sales_touch: datetime | None, evaluated_at: datetime
) -> int | None:
    """Whole days of sales silence, or `None` if there has never been a touch.

    `None` is a distinct answer from a large number, and the caller must decide
    what to do with it. The detector treats it as "does not fire": we cannot tell
    "never contacted" apart from "activity history not loaded", and firing on
    absent data is how a detector earns a reputation for false positives.

    Raises:
        CalculationError: if the most recent touch is in the future relative to the
            evaluation instant, which means the caller mixed up its clocks.
    """
    if latest_sales_touch is None:
        return None
    if latest_sales_touch.tzinfo is None or evaluated_at.tzinfo is None:
        raise CalculationError("both timestamps must be timezone-aware")

    delta = evaluated_at - latest_sales_touch
    if delta.days < 0:
        raise CalculationError(
            f"latest sales touch {latest_sales_touch.isoformat()} is after the evaluation "
            f"instant {evaluated_at.isoformat()}"
        )
    return delta.days


def week_over_week_growth(*, earlier: int, later: int) -> Decimal:
    """Growth from one period to the next, as a ratio: 1250 -> 1750 is `0.4000`.

    Raises:
        CalculationError: on a negative count, or on a zero baseline. Growth from
            zero is not infinite, it is undefined — and a first week of usage is
            not evidence of a stall. The caller handles that case explicitly
            rather than receiving a large number that looks like a signal.
    """
    if earlier < 0 or later < 0:
        raise CalculationError(f"usage counts must be non-negative, got {earlier} and {later}")
    if earlier == 0:
        raise CalculationError("growth from a zero baseline is undefined")

    return ((Decimal(later) - Decimal(earlier)) / Decimal(earlier)).quantize(GROWTH_PRECISION)
