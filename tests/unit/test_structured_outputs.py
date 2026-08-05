"""Structured-output schemas and the citation gate.

The invariants encoded in these schemas are the ones a plausible-but-wrong response
would violate: a plan with no steps, a source that does not exist, a single
hypothesis, a hypothesis that cites nothing. Each is rejected at the boundary rather
than handled downstream.

Citation *existence* cannot be a schema rule -- a schema has no way to know which
evidence ids are in workflow state -- so it is tested here against
`validate_citations`, which runs before anything is persisted.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from revenue_sentinel.agents.citations import validate_citations
from revenue_sentinel.core.errors import FabricatedCitationError
from revenue_sentinel.intelligence.schemas import (
    EvidenceRequest,
    EvidenceSelection,
    EvidenceSourceName,
    HypothesisDraft,
    HypothesisSet,
    InvestigationPlan,
    PlanStep,
)


def a_step(
    order: int = 1, source: EvidenceSourceName = EvidenceSourceName.CRM_OPPORTUNITY
) -> PlanStep:
    return PlanStep(order=order, source=source, objective="establish something")


def a_plan(steps: tuple[PlanStep, ...] | None = None) -> InvestigationPlan:
    return InvestigationPlan(steps=steps or (a_step(),), rationale="because")


def a_hypothesis(rank: int = 1, cites: tuple[str, ...] = ("EV-001",)) -> HypothesisDraft:
    return HypothesisDraft(
        rank=rank, statement="a statement", confidence=Decimal("0.5000"), cites=cites
    )


# ---------------------------------------------------------------------------
# InvestigationPlan
# ---------------------------------------------------------------------------
def test_a_minimal_plan_is_valid() -> None:
    assert len(a_plan().steps) == 1


def test_a_plan_with_no_steps_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InvestigationPlan(steps=(), rationale="because")


def test_a_plan_with_seven_steps_is_rejected() -> None:
    """The ceiling is enforced twice -- `order <= 6` on the step and `max_length=6`
    on the tuple -- so construction fails at the first violation either way."""
    with pytest.raises(ValidationError):
        steps = tuple(
            a_step(order=index, source=source)
            for index, source in enumerate(list(EvidenceSourceName) * 2, start=1)
        )[:7]
        InvestigationPlan(steps=steps, rationale="because")


def test_a_plan_naming_an_unknown_source_is_rejected() -> None:
    """Injection defence layer 4: the vocabulary is closed."""
    with pytest.raises(ValidationError):
        InvestigationPlan.model_validate(
            {
                "steps": [{"order": 1, "source": "run_sql", "objective": "everything"}],
                "rationale": "because",
            }
        )


def test_plan_step_orders_must_be_contiguous() -> None:
    steps = (a_step(1), a_step(3, EvidenceSourceName.PRODUCT_USAGE))
    with pytest.raises(ValidationError, match="no gaps"):
        InvestigationPlan(steps=steps, rationale="because")


def test_a_plan_must_not_consult_the_same_source_twice() -> None:
    steps = (a_step(1), a_step(2))
    with pytest.raises(ValidationError, match="same source twice"):
        InvestigationPlan(steps=steps, rationale="because")


def test_a_plan_with_an_empty_objective_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PlanStep(order=1, source=EvidenceSourceName.SUPPORT, objective="")


def test_the_permitted_source_set_is_the_allowlist() -> None:
    plan = a_plan((a_step(1), a_step(2, EvidenceSourceName.SUPPORT)))
    assert plan.permitted_sources == {
        EvidenceSourceName.CRM_OPPORTUNITY,
        EvidenceSourceName.SUPPORT,
    }


def test_extra_fields_are_forbidden_on_every_structured_output() -> None:
    """A model that invents a field misunderstood the contract; ignoring it silently
    is how a misunderstanding becomes a wrong screen."""
    with pytest.raises(ValidationError):
        InvestigationPlan.model_validate(
            {
                "steps": [{"order": 1, "source": "support_get_open_issues", "objective": "x"}],
                "rationale": "because",
                "confidence": 0.9,
            }
        )


# ---------------------------------------------------------------------------
# EvidenceSelection
# ---------------------------------------------------------------------------
def test_a_selection_within_the_plan_is_accepted() -> None:
    selection = EvidenceSelection(
        requests=(EvidenceRequest(source=EvidenceSourceName.SUPPORT, reason="check"),)
    )
    selection.validate_against_plan(frozenset({EvidenceSourceName.SUPPORT}))


def test_a_selection_outside_the_plan_is_rejected() -> None:
    """The schema constrains the vocabulary; this constrains it to *this* investigation."""
    selection = EvidenceSelection(
        requests=(EvidenceRequest(source=EvidenceSourceName.SUPPORT, reason="check"),)
    )
    with pytest.raises(ValueError, match="outside the plan"):
        selection.validate_against_plan(frozenset({EvidenceSourceName.PRODUCT_USAGE}))


def test_an_empty_selection_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceSelection(requests=())


def test_a_selection_beyond_the_request_ceiling_is_rejected() -> None:
    requests = tuple(
        EvidenceRequest(source=EvidenceSourceName.SUPPORT, reason="again") for _ in range(9)
    )
    with pytest.raises(ValidationError):
        EvidenceSelection(requests=requests)


# ---------------------------------------------------------------------------
# HypothesisSet
# ---------------------------------------------------------------------------
def test_two_hypotheses_are_valid() -> None:
    assert len(HypothesisSet(hypotheses=(a_hypothesis(1), a_hypothesis(2))).hypotheses) == 2


@pytest.mark.parametrize("count", [0, 1, 5])
def test_hypothesis_counts_outside_two_to_four_are_rejected(count: int) -> None:
    """`rank <= 4` and `max_length=4` both apply, so a fifth hypothesis is refused at
    whichever check it reaches first."""
    with pytest.raises(ValidationError):
        hypotheses = tuple(a_hypothesis(rank=index) for index in range(1, count + 1))
        HypothesisSet(hypotheses=hypotheses)


def test_a_hypothesis_citing_nothing_is_rejected() -> None:
    with pytest.raises(ValidationError):
        HypothesisDraft(rank=1, statement="x", confidence=Decimal("0.5"), cites=())


@pytest.mark.parametrize("bad", ["EV-1", "ev-001", "EV-0001", "EVIDENCE-001", ""])
def test_a_malformed_citation_reference_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        a_hypothesis(cites=(bad,))


@pytest.mark.parametrize("bad", [Decimal("-0.01"), Decimal("1.01")])
def test_confidence_outside_zero_to_one_is_rejected(bad: Decimal) -> None:
    with pytest.raises(ValidationError):
        HypothesisDraft(rank=1, statement="x", confidence=bad, cites=("EV-001",))


def test_hypothesis_ranks_must_be_contiguous() -> None:
    with pytest.raises(ValidationError, match="no gaps"):
        HypothesisSet(hypotheses=(a_hypothesis(1), a_hypothesis(3)))


def test_the_cited_reference_set_is_exposed() -> None:
    hypotheses = HypothesisSet(
        hypotheses=(a_hypothesis(1, ("EV-001", "EV-002")), a_hypothesis(2, ("EV-002",)))
    )
    assert hypotheses.cited_refs == {"EV-001", "EV-002"}


# ---------------------------------------------------------------------------
# The citation gate
# ---------------------------------------------------------------------------
def test_citations_that_all_exist_are_accepted() -> None:
    hypotheses = HypothesisSet(
        hypotheses=(a_hypothesis(1, ("EV-001",)), a_hypothesis(2, ("EV-002",)))
    )
    validate_citations(hypotheses, frozenset({"EV-001", "EV-002", "EV-003"}))


def test_a_fabricated_citation_is_rejected() -> None:
    """The anti-hallucination gate. Nothing downstream ever sees this set."""
    hypotheses = HypothesisSet(
        hypotheses=(a_hypothesis(1, ("EV-001",)), a_hypothesis(2, ("EV-999",)))
    )

    with pytest.raises(FabricatedCitationError) as caught:
        validate_citations(hypotheses, frozenset({"EV-001"}))

    assert caught.value.unknown_refs == ("EV-999",)
    assert "EV-999" in str(caught.value)


def test_the_error_names_every_fabricated_reference_at_once() -> None:
    """One round trip for whoever is debugging a prompt, not one per bad citation."""
    hypotheses = HypothesisSet(
        hypotheses=(a_hypothesis(1, ("EV-998", "EV-999")), a_hypothesis(2, ("EV-001",)))
    )

    with pytest.raises(FabricatedCitationError) as caught:
        validate_citations(hypotheses, frozenset({"EV-001"}))

    assert set(caught.value.unknown_refs) == {"EV-998", "EV-999"}


def test_no_known_evidence_at_all_rejects_every_citation() -> None:
    hypotheses = HypothesisSet(hypotheses=(a_hypothesis(1), a_hypothesis(2)))
    with pytest.raises(FabricatedCitationError):
        validate_citations(hypotheses, frozenset())
