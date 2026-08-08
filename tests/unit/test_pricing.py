"""Pricing arithmetic, proven to the microdollar without spending anything.

This is the module that lets the project claim its cost accounting works while having
never made a live API call. `cost_of` is pure, so every figure below is checked against
the published table with explicit token inputs -- **no `model_calls` row is fabricated to
manufacture a non-zero cost** (ADR-0013, ADR-0020).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from revenue_sentinel.core.errors import CalculationError
from revenue_sentinel.cost import routing
from revenue_sentinel.cost.pricing import (
    PRICE_TABLE,
    PRICING_VERSION,
    UnknownModelError,
    cost_of,
    worst_case_cost,
)


def test_a_known_model_prices_to_the_microdollar() -> None:
    """1M in + 1M out on Opus 5 = $5.00 + $25.00."""
    assert cost_of(
        model_id="claude-opus-5", input_tokens=1_000_000, output_tokens=1_000_000
    ) == Decimal("30.000000")


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("claude-opus-5", Decimal("0.030000")),
        ("claude-sonnet-5", Decimal("0.018000")),
        ("claude-haiku-4-5", Decimal("0.006000")),
    ],
)
def test_each_model_prices_from_its_own_row(model_id: str, expected: Decimal) -> None:
    """1000 in + 1000 out. Haiku is 5x cheaper than Opus, and the table says so."""
    assert cost_of(model_id=model_id, input_tokens=1_000, output_tokens=1_000) == expected


def test_zero_tokens_cost_exactly_zero() -> None:
    """The fixture-mode figure. **True, not a placeholder** -- zero was consumed."""
    assert cost_of(model_id="claude-opus-5", input_tokens=0, output_tokens=0) == Decimal("0.000000")


def test_sub_cent_costs_survive_rounding() -> None:
    """The reason `NUMERIC(12, 6)` exists.

    A single small Haiku call rounds to $0.00 at two decimal places, which would show
    real spend as free. At six it is visible.
    """
    tiny = cost_of(model_id="claude-haiku-4-5", input_tokens=100, output_tokens=10)

    assert tiny > Decimal("0")
    assert tiny.quantize(Decimal("0.01")) == Decimal("0.00")
    assert tiny == Decimal("0.000150")


def test_cache_reads_are_cheaper_than_fresh_input() -> None:
    fresh = cost_of(model_id="claude-opus-5", input_tokens=10_000, output_tokens=0)
    cached = cost_of(
        model_id="claude-opus-5", input_tokens=0, output_tokens=0, cache_read_tokens=10_000
    )

    assert cached == fresh / 10
    assert cached == Decimal("0.005000")


def test_cache_writes_cost_more_than_fresh_input() -> None:
    fresh = cost_of(model_id="claude-opus-5", input_tokens=10_000, output_tokens=0)
    written = cost_of(
        model_id="claude-opus-5", input_tokens=0, output_tokens=0, cache_write_tokens=10_000
    )

    assert written == (fresh * Decimal("1.25")).quantize(Decimal("0.000001"))


def test_an_unpriced_model_is_refused_rather_than_guessed_at() -> None:
    with pytest.raises(UnknownModelError, match="Refusing to estimate"):
        cost_of(model_id="claude-imaginary-9", input_tokens=1, output_tokens=1)


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "cache_read_tokens"])
def test_negative_tokens_are_refused(field: str) -> None:
    kwargs: dict[str, object] = {
        "model_id": "claude-opus-5",
        "input_tokens": 0,
        "output_tokens": 0,
        field: -1,
    }
    with pytest.raises(CalculationError, match="cannot be negative"):
        cost_of(**kwargs)  # type: ignore[arg-type]


def test_pricing_is_deterministic() -> None:
    """Same inputs, same figure -- otherwise a recorded cost could not be recomputed."""
    figures = {
        cost_of(model_id="claude-opus-5", input_tokens=12_345, output_tokens=6_789)
        for _ in range(20)
    }
    assert len(figures) == 1


def test_the_introductory_sonnet_price_is_deliberately_absent() -> None:
    """A price that changes on a date would make the same inputs produce different
    figures depending on when the function ran. That is what `pricing_version` prevents,
    so the standard rate is encoded and a new version is published when it lapses."""
    assert PRICE_TABLE["claude-sonnet-5"].input_usd == Decimal("3.00")
    assert PRICE_TABLE["claude-sonnet-5"].output_usd == Decimal("15.00")
    assert PRICING_VERSION == "pricing/2026-08"


# ---------------------------------------------------------------------------
# Worst-case reservation (ADR-0019)
# ---------------------------------------------------------------------------
def test_the_worst_case_assumes_the_full_output_ceiling() -> None:
    """Output tokens are unknowable before the call, so the bound assumes the maximum."""
    reserved = worst_case_cost(
        model_id="claude-opus-5", input_tokens=1_000, max_output_tokens=2_000
    )
    actual = cost_of(model_id="claude-opus-5", input_tokens=1_000, output_tokens=200)

    assert reserved > actual
    assert reserved == cost_of(model_id="claude-opus-5", input_tokens=1_000, output_tokens=2_000)


def test_the_reservation_is_never_below_the_actual_cost() -> None:
    """The property that makes over-reservation the safe error direction."""
    for output in (0, 1, 500, 2_000):
        reserved = worst_case_cost(
            model_id="claude-opus-5", input_tokens=1_000, max_output_tokens=2_000
        )
        actual = cost_of(model_id="claude-opus-5", input_tokens=1_000, output_tokens=output)
        assert reserved >= actual


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def test_every_llm_call_site_has_a_route() -> None:
    """A new node must not default to a model -- that is how cost surprises happen."""
    from revenue_sentinel.orchestration.nodes import NODE_SEQUENCE

    deterministic = {"calculate_impact", "evaluate_policy"}
    llm_nodes = set(NODE_SEQUENCE) - deterministic

    assert llm_nodes == set(routing.ROUTING_TABLE)


def test_an_unrouted_call_site_raises() -> None:
    with pytest.raises(routing.UnroutedCallSiteError, match="must not default"):
        routing.route_for("some_new_node")


def test_every_routed_model_has_a_published_price() -> None:
    """A route to an unpriced model would be a budget check that cannot run."""
    for route in routing.ROUTING_TABLE.values():
        assert route.model_id in PRICE_TABLE
        assert route.max_output_tokens > 0


def test_routing_matches_the_cost_governance_document() -> None:
    """`docs/cost-governance.md` §3. A routing table that drifts from its documentation
    is a cost model nobody can predict."""
    documented = {
        "plan_investigation": ("claude-opus-5", "high"),
        "collect_evidence": ("claude-opus-5", "medium"),
        "generate_hypotheses": ("claude-opus-5", "high"),
        "draft_interventions": ("claude-opus-5", "high"),
    }

    actual = {node: (route.model_id, route.effort) for node, route in routing.ROUTING_TABLE.items()}
    assert actual == documented
