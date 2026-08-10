"""The bound on concurrent `GLOBAL` budget overshoot (ADR-0026).

v1 does not implement atomic reservations, and the reason is written down rather than
shrugged at: a row lock held across a model call is worse than the race it fixes, and a
reservation ledger recreates the claimed-but-unresolved failure mode this project already
has tooling for.

What makes that acceptable rather than lazy is that the exposure is *bounded* and the
bound is computed by code these tests pin -- not described in prose.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from revenue_sentinel.cost.governor import CostGovernor

WORST_CASE = Decimal("0.084705")
"""A real worst-case reservation from the golden run's strategist call."""


def test_a_single_run_cannot_overshoot_at_all() -> None:
    """The guarantee serialization within a run actually provides."""
    assert CostGovernor.overshoot_bound(1, WORST_CASE) == Decimal("0.000000")


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        (2, "0.084705"),
        (3, "0.169410"),
        (10, "0.762345"),
    ],
)
def test_the_bound_grows_with_one_fewer_than_the_racing_runs(runs: int, expected: str) -> None:
    assert CostGovernor.overshoot_bound(runs, WORST_CASE) == Decimal(expected)


def test_the_bound_is_decimal_all_the_way_through() -> None:
    """No float ever touches money (ADR-0020)."""
    bound = CostGovernor.overshoot_bound(4, WORST_CASE)

    assert isinstance(bound, Decimal)
    assert bound == Decimal("0.254115")
    assert str(bound) == "0.254115", "six decimal places, like every other figure"


def test_the_bound_is_deterministic() -> None:
    first = CostGovernor.overshoot_bound(7, WORST_CASE)
    assert all(CostGovernor.overshoot_bound(7, WORST_CASE) == first for _ in range(5))


def test_fewer_than_one_run_is_refused() -> None:
    """Zero concurrent runs is not a smaller risk; it is a nonsense question."""
    with pytest.raises(ValueError, match="concurrent_runs must be >= 1"):
        CostGovernor.overshoot_bound(0, WORST_CASE)

    with pytest.raises(ValueError, match="concurrent_runs must be >= 1"):
        CostGovernor.overshoot_bound(-3, WORST_CASE)


def test_a_negative_reservation_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        CostGovernor.overshoot_bound(2, Decimal("-0.01"))


def test_a_zero_reservation_bounds_the_overshoot_at_zero() -> None:
    """Fixture mode reserves nothing it cannot spend, and spends nothing."""
    assert CostGovernor.overshoot_bound(50, Decimal("0")) == Decimal("0.000000")
