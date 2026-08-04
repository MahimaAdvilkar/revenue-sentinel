"""The two window calculations detection and impact assessment share.

Both feed decisions further down: `days_inactive` selects a stall-risk band, and
`usage_growth` selects a usage offset. An error here would move a dollar figure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from revenue_sentinel.analytics.windows import (
    days_since_last_sales_touch,
    week_over_week_growth,
)
from revenue_sentinel.core.errors import CalculationError

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Days since the last sales touch
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("days", [0, 1, 13, 14, 15, 90])
def test_whole_days_are_counted(days: int) -> None:
    assert (
        days_since_last_sales_touch(latest_sales_touch=NOW - timedelta(days=days), evaluated_at=NOW)
        == days
    )


def test_partial_days_round_down() -> None:
    """13 days and 23 hours is 13 days of silence, not 14.

    Rounding up would make the detector fire a day early, which is the kind of
    off-by-one that only shows up as an unexplainable extra incident.
    """
    almost = NOW - timedelta(days=13, hours=23, minutes=59)
    assert days_since_last_sales_touch(latest_sales_touch=almost, evaluated_at=NOW) == 13


def test_no_recorded_touch_returns_none_not_infinity() -> None:
    """`None` is a distinct answer: we cannot tell "never contacted" from
    "history not loaded", and the caller must decide."""
    assert days_since_last_sales_touch(latest_sales_touch=None, evaluated_at=NOW) is None


def test_a_touch_in_the_future_raises() -> None:
    with pytest.raises(CalculationError, match="after the evaluation instant"):
        days_since_last_sales_touch(latest_sales_touch=NOW + timedelta(days=1), evaluated_at=NOW)


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(CalculationError, match="timezone-aware"):
        days_since_last_sales_touch(
            latest_sales_touch=datetime(2026, 7, 18, 12, 0),  # noqa: DTZ001 -- the point
            evaluated_at=NOW,
        )


# ---------------------------------------------------------------------------
# Week-over-week growth
# ---------------------------------------------------------------------------
def test_the_golden_scenario_growth_is_exactly_forty_percent() -> None:
    assert week_over_week_growth(earlier=1250, later=1750) == Decimal("0.4000")


@pytest.mark.parametrize(
    ("earlier", "later", "expected"),
    [
        (100, 100, Decimal("0.0000")),
        (100, 139, Decimal("0.3900")),
        (100, 140, Decimal("0.4000")),
        (100, 200, Decimal("1.0000")),
        (100, 88, Decimal("-0.1200")),
        (100, 0, Decimal("-1.0000")),
    ],
)
def test_growth_ratios(earlier: int, later: int, expected: Decimal) -> None:
    assert week_over_week_growth(earlier=earlier, later=later) == expected


def test_growth_is_decimal_not_float() -> None:
    result = week_over_week_growth(earlier=3, later=4)
    assert isinstance(result, Decimal)
    assert result == Decimal("0.3333")


def test_a_zero_baseline_raises_rather_than_returning_a_huge_number() -> None:
    """Growth from zero is undefined, not infinite. A first week of usage is not
    evidence of a stall, and returning a large number would make it look like one."""
    with pytest.raises(CalculationError, match="zero baseline"):
        week_over_week_growth(earlier=0, later=1750)


def test_zero_to_zero_also_raises() -> None:
    with pytest.raises(CalculationError, match="zero baseline"):
        week_over_week_growth(earlier=0, later=0)


@pytest.mark.parametrize(("earlier", "later"), [(-1, 100), (100, -1)])
def test_negative_counts_raise(earlier: int, later: int) -> None:
    with pytest.raises(CalculationError, match="non-negative"):
        week_over_week_growth(earlier=earlier, later=later)
