"""Intervention scoring: the arithmetic, and the structural guarantee around it.

The claim Session 5 makes is "the LLM drafts, tested code ranks". These tests hold both
halves to account -- the numbers to the cent, and the fact that a model cannot reach
them.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from revenue_sentinel.analytics.intervention_scoring import (
    EffortBand,
    RecoveryBand,
    composite,
    expected_value,
    rank,
    score_intervention,
)
from revenue_sentinel.core.errors import CalculationError
from revenue_sentinel.domain.enums import ProposedAction, RiskTier

AT_RISK = Decimal("32130.00")
WEIGHTED = Decimal("108000.00")


# ---------------------------------------------------------------------------
# Arithmetic, to the cent
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("band", "expected"),
    [
        (RecoveryBand.LOW, Decimal("3213.00")),
        (RecoveryBand.MEDIUM, Decimal("9639.00")),
        (RecoveryBand.HIGH, Decimal("16065.00")),
    ],
)
def test_expected_value_is_a_share_of_at_risk_value(band: RecoveryBand, expected: Decimal) -> None:
    assert expected_value(AT_RISK, band) == expected


def test_expected_value_of_nothing_at_risk_is_nothing() -> None:
    assert expected_value(Decimal("0.00"), RecoveryBand.HIGH) == Decimal("0.00")


def test_a_negative_at_risk_value_is_refused() -> None:
    with pytest.raises(CalculationError, match="negative"):
        expected_value(Decimal("-1.00"), RecoveryBand.LOW)


def test_composite_is_value_per_unit_of_effort_and_risk() -> None:
    """(16065/108000)*100 / (1+1+1) = 14.875 / 3 = 4.9583... -> 4.96"""
    assert composite(
        value=Decimal("16065.00"),
        effort_score=Decimal("1.00"),
        risk_score=Decimal("1.00"),
        weighted_value=WEIGHTED,
    ) == Decimal("4.96")


def test_composite_is_independent_of_deal_size() -> None:
    """The same intervention on a large and a small deal scores the same.

    Otherwise the ranking would restate which deal is bigger rather than which action
    is better, and every incident would recommend the same thing.
    """
    big = composite(
        value=Decimal("16065.00"),
        effort_score=Decimal("2.00"),
        risk_score=Decimal("3.00"),
        weighted_value=WEIGHTED,
    )
    small = composite(
        value=Decimal("1606.50"),
        effort_score=Decimal("2.00"),
        risk_score=Decimal("3.00"),
        weighted_value=Decimal("10800.00"),
    )
    assert big == small


def test_a_zero_weighted_value_is_refused_rather_than_dividing_by_zero() -> None:
    with pytest.raises(CalculationError, match="weighted value"):
        composite(
            value=Decimal("1.00"),
            effort_score=Decimal("1.00"),
            risk_score=Decimal("0.00"),
            weighted_value=Decimal("0.00"),
        )


# ---------------------------------------------------------------------------
# Risk comes from the tier, not from the model
# ---------------------------------------------------------------------------
def test_risk_is_derived_from_the_policy_tier() -> None:
    prohibited = score_intervention(
        title="Email everyone",
        action=ProposedAction.SEND_EMAIL_DIRECT,
        recovery=RecoveryBand.HIGH,
        effort=EffortBand.LOW,
        at_risk_value=AT_RISK,
        weighted_value=WEIGHTED,
    )
    internal = score_intervention(
        title="Book a call",
        action=ProposedAction.CRM_TASK,
        recovery=RecoveryBand.HIGH,
        effort=EffortBand.LOW,
        at_risk_value=AT_RISK,
        weighted_value=WEIGHTED,
    )

    assert prohibited.risk_tier is RiskTier.PROHIBITED
    assert internal.risk_tier is RiskTier.INTERNAL_REVERSIBLE
    assert prohibited.risk_score > internal.risk_score


def test_a_prohibited_action_never_outranks_a_permitted_one_at_equal_value() -> None:
    """Identical recovery and effort; the tier alone must settle it."""
    scored = tuple(
        score_intervention(
            title=title,
            action=action,
            recovery=RecoveryBand.HIGH,
            effort=EffortBand.LOW,
            at_risk_value=AT_RISK,
            weighted_value=WEIGHTED,
        )
        for title, action in (
            ("Prohibited", ProposedAction.SEND_EMAIL_DIRECT),
            ("Permitted", ProposedAction.CRM_TASK),
        )
    )

    assert rank(scored)[0].title == "Permitted"


# ---------------------------------------------------------------------------
# Ordering is total and stable
# ---------------------------------------------------------------------------
def test_ranking_is_stable_across_input_order() -> None:
    """Shuffling the drafts must not change the result. A ranking that depended on
    the order a model wrote them in would not be a ranking."""
    scored = tuple(
        score_intervention(
            title=title,
            action=ProposedAction.CRM_TASK,
            recovery=recovery,
            effort=EffortBand.LOW,
            at_risk_value=AT_RISK,
            weighted_value=WEIGHTED,
        )
        for title, recovery in (
            ("a", RecoveryBand.LOW),
            ("b", RecoveryBand.HIGH),
            ("c", RecoveryBand.MEDIUM),
        )
    )

    forward = [item.title for item in rank(scored)]
    backward = [item.title for item in rank(tuple(reversed(scored)))]

    assert forward == backward == ["b", "c", "a"]


def test_a_tie_is_broken_deterministically() -> None:
    """Two identical scores still produce one fixed order, on every machine."""
    scored = tuple(
        score_intervention(
            title=title,
            action=ProposedAction.CRM_TASK,
            recovery=RecoveryBand.HIGH,
            effort=EffortBand.LOW,
            at_risk_value=AT_RISK,
            weighted_value=WEIGHTED,
        )
        for title in ("zebra", "aardvark")
    )

    assert [item.title for item in rank(scored)] == ["aardvark", "zebra"]
    assert scored[0].composite_score == scored[1].composite_score


# ---------------------------------------------------------------------------
# The structural guarantee (rule 9)
# ---------------------------------------------------------------------------
def test_the_scorer_imports_nothing_from_the_model_layer() -> None:
    """Asserted against the AST, not against a convention.

    `import-linter` R3 already forbids `analytics/ -> intelligence/` and
    `analytics/ -> agents/` for the whole package. This checks the specific module the
    ranking claim rests on, so a future refactor that moved scoring elsewhere would
    have to move this test too and notice what it was giving up.
    """
    source = Path("src/revenue_sentinel/analytics/intervention_scoring.py").read_text()
    tree = ast.parse(source)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)

    assert not [name for name in imported if "intelligence" in name or "agents" in name]
