"""Investigation artifacts: evidence, hypotheses, impact, interventions.

Two invariants in this module are load-bearing for the product's credibility:

* A hypothesis cites evidence through `HypothesisEvidence`, a join to rows that
  actually exist. A fabricated citation cannot be represented.
* `ImpactAssessment.computed_by` is `DETERMINISTIC` and `inputs` records every input
  to the calculation, so any figure on screen can be recomputed by hand.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.base import (
    CurrencyCode,
    DomainModel,
    EvidenceRef,
    HypothesisRef,
    Money,
    NonEmptyStr,
    Probability,
    Score,
    UtcDatetime,
)
from revenue_sentinel.domain.enums import ActionType, ComputedBy, SourceSystem, TrustLevel


class EvidenceItem(DomainModel):
    """One retrieved fact. `content` is untrusted source data (rule 14)."""

    id: UUID
    run_id: UUID
    evidence_ref: EvidenceRef
    source_system: SourceSystem
    tool_name: NonEmptyStr
    retrieved_at: UtcDatetime
    content: JSONObject
    trust_level: TrustLevel = TrustLevel.UNTRUSTED


class Hypothesis(DomainModel):
    """A candidate explanation, ranked by the model's stated confidence."""

    id: UUID
    run_id: UUID
    hypothesis_ref: HypothesisRef
    statement: NonEmptyStr
    confidence: Probability
    rank: int = Field(ge=1)


class HypothesisEvidence(DomainModel):
    """Join row proving a hypothesis cites real evidence."""

    id: UUID
    hypothesis_id: UUID
    evidence_item_id: UUID


class ImpactAssessment(DomainModel):
    """The money figure, and everything that produced it.

    `computed_by` is `DETERMINISTIC` for every row this system writes. The field
    exists so a violation of rule 9 would be *visible in the data* rather than
    invisible, which is what makes the evaluation check meaningful.
    """

    id: UUID
    run_id: UUID
    method_version: NonEmptyStr
    pipeline_value: Money
    weighted_value: Money
    at_risk_value: Money
    currency: CurrencyCode
    inputs: JSONObject
    computed_by: ComputedBy = ComputedBy.DETERMINISTIC

    @model_validator(mode="after")
    def _values_are_ordered(self) -> ImpactAssessment:
        """At-risk cannot exceed weighted, and weighted cannot exceed pipeline.

        Arithmetic that violates this is wrong, not merely surprising, so it is
        rejected at the boundary rather than rendered in a dashboard.
        """
        if self.weighted_value > self.pipeline_value:
            raise ValueError("weighted_value exceeds pipeline_value")
        if self.at_risk_value > self.weighted_value:
            raise ValueError("at_risk_value exceeds weighted_value")
        return self


class Intervention(DomainModel):
    """A proposed action. Drafted by a model; **ranked by `analytics/`** (rule 9)."""

    id: UUID
    run_id: UUID
    rank: int = Field(ge=1)
    title: NonEmptyStr
    action_type: ActionType
    rationale: str
    expected_value: Money
    effort_score: Score
    risk_score: Score
    composite_score: Score
