"""Ranking interventions. **The model drafts; this ranks.** (rule 9, ADR-0003)

This module lives in `analytics/` for one structural reason: `import-linter` contract
R3 forbids `analytics/` from importing `intelligence/` or `agents/`. The ranking
therefore *cannot* be influenced by model output even by accident -- not because a
reviewer checked, but because the import would fail CI.

What the model is allowed to contribute is qualitative and banded: how much of the
at-risk value an intervention might recover, and how much effort it costs. It supplies
a band, never a number. Everything numeric below is computed here from tested tables.

Risk is not taken from the model at all. It is derived from the action's **policy
tier** (`governance/tiers.py`), so "how risky is this?" has exactly one answer in the
system and the strategy agent does not get a second opinion.

Bands rather than a fitted score, for the reason ADR-0008 gives: a step table can be
read and argued with, and its numbers were not chosen to make a demo rank prettily.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum, unique
from types import MappingProxyType
from typing import Final

from revenue_sentinel.core.errors import CalculationError
from revenue_sentinel.domain.enums import ProposedAction, RiskTier
from revenue_sentinel.governance import tiers

SCORING_VERSION: Final = "intervention_scoring/v1"

_MONEY = Decimal("0.01")
_SCORE = Decimal("0.01")


@unique
class RecoveryBand(StrEnum):
    """How much of the at-risk value this intervention could plausibly recover."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@unique
class EffortBand(StrEnum):
    """What it costs the team to do. Not a duration -- a band."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_RECOVERY_SHARE: Final[MappingProxyType[RecoveryBand, Decimal]] = MappingProxyType(
    {
        RecoveryBand.LOW: Decimal("0.10"),
        RecoveryBand.MEDIUM: Decimal("0.30"),
        RecoveryBand.HIGH: Decimal("0.50"),
    }
)
"""Share of the **at-risk** value, not of pipeline. Capped at 0.50 deliberately: no
single outreach recovers a majority of a stalled deal's risk, and a table that allowed
it would produce expected values a revenue leader would rightly disbelieve."""

_EFFORT_SCORE: Final[MappingProxyType[EffortBand, Decimal]] = MappingProxyType(
    {
        EffortBand.LOW: Decimal("1.00"),
        EffortBand.MEDIUM: Decimal("2.00"),
        EffortBand.HIGH: Decimal("4.00"),
    }
)
"""Higher is costlier. The step from medium to high is larger than low to medium
because effort tends to be superlinear once a task needs coordination."""

_RISK_SCORE_BY_TIER: Final[MappingProxyType[RiskTier, Decimal]] = MappingProxyType(
    {
        RiskTier.READ_OR_COMPUTE: Decimal("0.00"),
        RiskTier.INTERNAL_REVERSIBLE: Decimal("1.00"),
        RiskTier.CUSTOMER_FACING_OR_MATERIAL: Decimal("3.00"),
        RiskTier.PROHIBITED: Decimal("10.00"),
    }
)
"""Tier 3 is scored far above tier 2 rather than one step above it. A prohibited action
should never out-rank a permitted one on expected value alone, and this is what makes
that arithmetic rather than a special case."""


@dataclass(frozen=True, slots=True)
class ScoredIntervention:
    """One intervention with its computed figures.

    A dataclass rather than a hand-rolled class, and not only for brevity: LangGraph's
    checkpointer serialises workflow state, and it handles dataclasses. A plain class
    with `__slots__` fails with `Type is not msgpack serializable` the moment this
    reaches state -- which is a poor way to discover a design constraint.
    """

    title: str
    action: ProposedAction
    expected_value: Decimal
    effort_score: Decimal
    risk_score: Decimal
    risk_tier: RiskTier
    composite_score: Decimal


def expected_value(at_risk_value: Decimal, recovery: RecoveryBand) -> Decimal:
    """The share of at-risk value this intervention could recover, to the cent."""
    if at_risk_value < 0:
        raise CalculationError(f"at-risk value cannot be negative, got {at_risk_value}")
    return (at_risk_value * _RECOVERY_SHARE[recovery]).quantize(_MONEY)


def composite(
    *, value: Decimal, effort_score: Decimal, risk_score: Decimal, weighted_value: Decimal
) -> Decimal:
    """Value per unit of effort and risk, on a scale independent of deal size.

        composite = (value / weighted_value) * 100 / (effort + risk + 1)

    The `+ 1` keeps a zero-effort zero-risk action finite rather than infinite.
    Normalising by weighted value means the same intervention on a $180k deal and a
    $18k deal scores the same, so the ranking reflects the *intervention* rather than
    restating which deal is bigger.
    """
    if weighted_value <= 0:
        raise CalculationError(f"weighted value must be positive, got {weighted_value}")
    if effort_score < 0 or risk_score < 0:
        raise CalculationError("effort and risk scores must be non-negative")

    ratio = (value / weighted_value) * Decimal(100)
    return (ratio / (effort_score + risk_score + Decimal(1))).quantize(_SCORE)


def score_intervention(
    *,
    title: str,
    action: ProposedAction,
    recovery: RecoveryBand,
    effort: EffortBand,
    at_risk_value: Decimal,
    weighted_value: Decimal,
    fields_changed: frozenset[str] = frozenset(),
) -> ScoredIntervention:
    """Every number on one intervention, computed from bands and the impact figures."""
    tier, _ = tiers.classify(action, fields_changed=fields_changed)
    value = expected_value(at_risk_value, recovery)
    effort_score = _EFFORT_SCORE[effort]
    risk_score = _RISK_SCORE_BY_TIER[tier]

    return ScoredIntervention(
        title=title,
        action=action,
        expected_value=value,
        effort_score=effort_score,
        risk_score=risk_score,
        risk_tier=tier,
        composite_score=composite(
            value=value,
            effort_score=effort_score,
            risk_score=risk_score,
            weighted_value=weighted_value,
        ),
    )


def rank(interventions: tuple[ScoredIntervention, ...]) -> tuple[ScoredIntervention, ...]:
    """Highest composite first.

    Ties break on `(-composite, -expected_value, action value, title)` -- fully
    determined, so the same inputs produce the same order on every run and on every
    machine. A ranking that depended on dict ordering or float noise would make the
    demo irreproducible in the one place reproducibility is the claim.
    """
    return tuple(
        sorted(
            interventions,
            key=lambda item: (
                -item.composite_score,
                -item.expected_value,
                item.action.value,
                item.title,
            ),
        )
    )
