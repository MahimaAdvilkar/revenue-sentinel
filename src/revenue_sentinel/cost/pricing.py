"""What a model call costs. A pure function over a versioned price table.

**No database, no client, no network.** That is the whole point: the arithmetic can be
tested exhaustively without ever spending a cent, which is the only way this project can
claim its cost accounting works while having never made a live API call (ADR-0013).

Prices are **data with a version**, not constants (ADR-0020). Every `cost_entries` row
records the `pricing_version` that produced it, so a figure from last month can be
recomputed under the prices that were in force then rather than silently repriced by a
later table.

All arithmetic is `Decimal`. Float would introduce representation error into money, which
`docs/data-model.md` §1 forbids for exactly this reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final

from revenue_sentinel.core.errors import CalculationError

PRICING_VERSION: Final = "pricing/2026-08"
"""Bumped whenever a price changes. Never edit a published version's numbers in place --
that would rewrite history for every entry already stamped with it."""

MICRODOLLAR: Final = Decimal("0.000001")
"""`cost_entries.amount_usd` is `NUMERIC(12, 6)`. Six places because one Haiku call can
cost a small fraction of a cent, and rounding per call to cents would show $0.00 for real
spend."""

_PER_MILLION: Final = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Dollars per million tokens, from `docs/cost-governance.md` §3."""

    input_usd: Decimal
    output_usd: Decimal
    cache_read_multiplier: Decimal = Decimal("0.1")
    cache_write_multiplier: Decimal = Decimal("1.25")


PRICE_TABLE: Final[dict[str, ModelPrice]] = {
    "claude-opus-5": ModelPrice(input_usd=Decimal("5.00"), output_usd=Decimal("25.00")),
    "claude-sonnet-5": ModelPrice(input_usd=Decimal("3.00"), output_usd=Decimal("15.00")),
    "claude-haiku-4-5": ModelPrice(input_usd=Decimal("1.00"), output_usd=Decimal("5.00")),
}
"""Standard prices. The Sonnet introductory rate ($2.00/$10.00) expires 2026-08-31 and is
deliberately **not** encoded: a price that changes on a date would make the same inputs
produce different figures depending on when the function ran, which is precisely what
`pricing_version` exists to prevent. When it lapses, publish a new version."""


class UnknownModelError(CalculationError):
    """A model with no published price. Refused rather than guessed at."""

    def __init__(self, model_id: str) -> None:
        super().__init__(
            f"no price for {model_id!r} in {PRICING_VERSION}. Refusing to estimate a "
            f"cost for a model whose price is not published."
        )


def price_for(model_id: str) -> ModelPrice:
    price = PRICE_TABLE.get(model_id)
    if price is None:
        raise UnknownModelError(model_id)
    return price


def cost_of(
    *,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal:
    """The cost of one model call, to the microdollar.

    **Zero tokens produce exactly `0.000000`, and that is a true figure rather than a
    placeholder.** In fixture mode no tokens are consumed, so no money is spent; nothing
    here estimates what a live call *would* have cost.
    """
    for name, value in (
        ("input", input_tokens),
        ("output", output_tokens),
        ("cache_read", cache_read_tokens),
        ("cache_write", cache_write_tokens),
    ):
        if value < 0:
            raise CalculationError(f"{name} tokens cannot be negative, got {value}")

    price = price_for(model_id)
    total = (
        Decimal(input_tokens) * price.input_usd
        + Decimal(output_tokens) * price.output_usd
        + Decimal(cache_read_tokens) * price.input_usd * price.cache_read_multiplier
        + Decimal(cache_write_tokens) * price.input_usd * price.cache_write_multiplier
    ) / _PER_MILLION

    return total.quantize(MICRODOLLAR, rounding=ROUND_HALF_EVEN)


def worst_case_cost(*, model_id: str, input_tokens: int, max_output_tokens: int) -> Decimal:
    """The most this call could possibly cost, used to reserve budget before spending.

    Output tokens are unknowable before the call, so the bound assumes the configured
    maximum. This **over-reserves**: a call can be refused that would have fitted.

    That is the deliberate error direction (ADR-0019). A conservative refusal is
    explainable; a silent overspend is a budget that was never a budget.
    """
    return cost_of(model_id=model_id, input_tokens=input_tokens, output_tokens=max_output_tokens)
