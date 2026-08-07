"""Structured-output schemas.

Every LLM-backed node validates against one of these. There is no free-text parsing,
no regex over model output, and no `json.loads` on an unvalidated string (rule 4).

The invariants encoded here are the ones a plausible-but-wrong response would
violate: a plan with no steps, a source that does not exist, a hypothesis set with a
single hypothesis, a hypothesis that cites nothing. Each is rejected at the boundary
rather than handled downstream.

Citation *existence* cannot be checked here -- a schema has no way to know which
evidence ids are in workflow state. That check lives in `agents/citations.py` and
runs against state before anything is persisted.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum, unique
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from revenue_sentinel.analytics.intervention_scoring import EffortBand, RecoveryBand
from revenue_sentinel.domain.enums import ProposedAction

MIN_PLAN_STEPS: Final = 1
MAX_PLAN_STEPS: Final = 6
MIN_HYPOTHESES: Final = 2
MAX_HYPOTHESES: Final = 4
MAX_EVIDENCE_REQUESTS: Final = 8
MIN_INTERVENTIONS: Final = 3
MAX_INTERVENTIONS: Final = 5
TOP_INTERVENTIONS: Final = 3
"""The graph persists the three highest-scoring drafts. The model may offer up to five;
which three survive is decided by `analytics/`, not by the order they were written in."""
MAX_CHANGED_FIELDS: Final = 5


@unique
class EvidenceSourceName(StrEnum):
    """The sources an agent may consult -- injection defence layer 4.

    These names are deliberately the shape of the MCP tools that replace them in
    Session 4, so that session swaps the implementation behind the port rather than
    redesigning the agent. A model naming anything outside this set fails validation.
    """

    CRM_OPPORTUNITY = "crm_get_opportunity"
    CRM_ACTIVITIES = "crm_list_account_activities"
    PRODUCT_USAGE = "product_get_usage_summary"
    ENGAGEMENT = "engagement_get_email_activity"
    SUPPORT = "support_get_open_issues"


EvidenceRefStr = Annotated[str, StringConstraints(pattern=r"^EV-[0-9]{3}$")]
NonEmptyText = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class StructuredOutput(BaseModel):
    """Base for every model-produced object: immutable and closed.

    `extra="forbid"` matters more here than anywhere else in the codebase. A model
    that invents an extra field is a model that misunderstood the contract, and
    silently ignoring it is how a misunderstanding becomes a wrong screen.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class PlanStep(StructuredOutput):
    order: int = Field(ge=1, le=MAX_PLAN_STEPS)
    source: EvidenceSourceName
    objective: NonEmptyText


class InvestigationPlan(StructuredOutput):
    """What the planner produced. 1-6 steps, each naming a permitted source."""

    steps: tuple[PlanStep, ...] = Field(min_length=MIN_PLAN_STEPS, max_length=MAX_PLAN_STEPS)
    rationale: NonEmptyText

    @model_validator(mode="after")
    def _orders_are_contiguous_and_sources_unique(self) -> InvestigationPlan:
        orders = [step.order for step in self.steps]
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError(f"plan step orders must be 1..n with no gaps, got {orders}")
        sources = [step.source for step in self.steps]
        if len(set(sources)) != len(sources):
            raise ValueError("a plan must not consult the same source twice")
        return self

    @property
    def permitted_sources(self) -> frozenset[EvidenceSourceName]:
        """The allowlist the researcher is held to."""
        return frozenset(step.source for step in self.steps)


class EvidenceRequest(StructuredOutput):
    source: EvidenceSourceName
    reason: NonEmptyText


class EvidenceSelection(StructuredOutput):
    """What the researcher chose to gather.

    Constrained to the plan's sources by `validate_against_plan` -- the schema alone
    cannot know what the plan said.
    """

    requests: tuple[EvidenceRequest, ...] = Field(min_length=1, max_length=MAX_EVIDENCE_REQUESTS)

    def validate_against_plan(self, permitted: frozenset[EvidenceSourceName]) -> None:
        """Reject any source the plan did not name."""
        chosen = {request.source for request in self.requests}
        forbidden = chosen - permitted
        if forbidden:
            raise ValueError(
                "evidence selection names sources outside the plan: "
                f"{sorted(source.value for source in forbidden)}"
            )


class HypothesisDraft(StructuredOutput):
    rank: int = Field(ge=1, le=MAX_HYPOTHESES)
    statement: NonEmptyText
    confidence: Decimal = Field(ge=0, le=1, max_digits=5, decimal_places=4)
    cites: tuple[EvidenceRefStr, ...] = Field(min_length=1)


class HypothesisSet(StructuredOutput):
    """2-4 hypotheses, each citing at least one evidence reference."""

    hypotheses: tuple[HypothesisDraft, ...] = Field(
        min_length=MIN_HYPOTHESES, max_length=MAX_HYPOTHESES
    )

    @model_validator(mode="after")
    def _ranks_are_contiguous(self) -> HypothesisSet:
        ranks = sorted(hypothesis.rank for hypothesis in self.hypotheses)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError(f"hypothesis ranks must be 1..n with no gaps, got {ranks}")
        return self

    @property
    def cited_refs(self) -> frozenset[str]:
        return frozenset(ref for hypothesis in self.hypotheses for ref in hypothesis.cites)


class InterventionDraft(StructuredOutput):
    """One proposed intervention. **Qualitative only.**

    There is no monetary field here and there never will be. The model supplies a
    `recovery` band and an `effort` band; `analytics/intervention_scoring.py` turns
    those into expected value, effort, risk, and the composite score (rule 9). A model
    that wanted to inflate an intervention's ranking has no field to do it in.

    `action` is a `ProposedAction`, which is wider than what the system can execute.
    The model may propose sending an email directly; the policy layer refuses it and
    records the refusal. Constraining the schema to only-permissible actions would
    hide that the model asked.
    """

    title: NonEmptyText
    action: ProposedAction
    rationale: NonEmptyText
    recovery: RecoveryBand
    effort: EffortBand
    target_ref: Annotated[str, StringConstraints(pattern=r"^(ACC|OPP|INC)-[0-9]{3,6}$")]
    fields_changed: tuple[Annotated[str, StringConstraints(min_length=1, max_length=64)], ...] = (
        Field(default=(), max_length=MAX_CHANGED_FIELDS)
    )
    """Only meaningful for `crm_field_update`. Empty for everything else -- and an
    empty set on a field update classifies as tier 3, because an unspecified mutation
    cannot be assessed."""


class InterventionSet(StructuredOutput):
    """3-5 drafted interventions. The scorer ranks them; the graph keeps the top 3."""

    interventions: tuple[InterventionDraft, ...] = Field(
        min_length=MIN_INTERVENTIONS, max_length=MAX_INTERVENTIONS
    )

    @model_validator(mode="after")
    def _titles_are_distinct(self) -> InterventionSet:
        titles = [draft.title for draft in self.interventions]
        if len(set(titles)) != len(titles):
            raise ValueError("interventions must be distinct; two share a title")
        return self
