"""Evidence, hypotheses, impact assessments, and interventions.

`hypothesis_evidence` is a join table with foreign keys to both sides. That is what
makes "every hypothesis cites real evidence" a schema guarantee rather than a
validation step someone could skip: a fabricated citation has no row to point at.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from revenue_sentinel.db.base import (
    Base,
    CreatedAtMixin,
    json_object,
    long_text,
    money,
    pg_enum,
    probability,
    score,
    short_text,
    timestamp_tz,
    uuid_fk,
    uuid_pk,
)
from revenue_sentinel.domain.enums import ComputedBy, ProposedAction, SourceSystem, TrustLevel


class EvidenceItem(Base, CreatedAtMixin):
    """`content` is untrusted source data (rule 14)."""

    __tablename__ = "evidence_items"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    evidence_ref: Mapped[str] = mapped_column(sa.String(16))
    source_system: Mapped[SourceSystem] = mapped_column(pg_enum(SourceSystem, "source_system"))
    tool_name: Mapped[short_text]
    retrieved_at: Mapped[timestamp_tz]
    content: Mapped[json_object]
    trust_level: Mapped[TrustLevel] = mapped_column(
        pg_enum(TrustLevel, "trust_level"), server_default=TrustLevel.UNTRUSTED.value
    )

    __table_args__ = (
        sa.UniqueConstraint("run_id", "evidence_ref", name="uq_evidence_items_run_id_evidence_ref"),
    )


class Hypothesis(Base, CreatedAtMixin):
    __tablename__ = "hypotheses"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    hypothesis_ref: Mapped[str] = mapped_column(sa.String(16))
    statement: Mapped[long_text]
    confidence: Mapped[probability]
    rank: Mapped[int] = mapped_column(sa.Integer)

    __table_args__ = (
        sa.UniqueConstraint("run_id", "hypothesis_ref", name="uq_hypotheses_run_id_hypothesis_ref"),
        sa.UniqueConstraint("run_id", "rank", name="uq_hypotheses_run_id_rank"),
        sa.CheckConstraint("rank >= 1", name="rank_positive"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_in_range"),
    )


class HypothesisEvidence(Base, CreatedAtMixin):
    """Join row proving a hypothesis cites evidence that exists."""

    __tablename__ = "hypothesis_evidence"

    id: Mapped[uuid_pk]
    hypothesis_id: Mapped[uuid_fk] = mapped_column(
        sa.ForeignKey("hypotheses.id", ondelete="CASCADE")
    )
    evidence_item_id: Mapped[uuid_fk] = mapped_column(
        sa.ForeignKey("evidence_items.id", ondelete="CASCADE")
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "hypothesis_id",
            "evidence_item_id",
            name="uq_hypothesis_evidence_hypothesis_id_evidence_item_id",
        ),
    )


class ImpactAssessment(Base, CreatedAtMixin):
    """`inputs` stores every input to the calculation, so any figure shown in the
    dashboard can be recomputed and verified by hand."""

    __tablename__ = "impact_assessments"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid_fk] = mapped_column(
        sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), unique=True
    )
    method_version: Mapped[str] = mapped_column(sa.String(32))
    pipeline_value: Mapped[money]
    weighted_value: Mapped[money]
    at_risk_value: Mapped[money]
    currency: Mapped[str] = mapped_column(sa.String(3))
    inputs: Mapped[json_object]
    computed_by: Mapped[ComputedBy] = mapped_column(
        pg_enum(ComputedBy, "computed_by"), server_default=ComputedBy.DETERMINISTIC.value
    )

    __table_args__ = (
        sa.CheckConstraint(
            "pipeline_value >= 0 AND weighted_value >= 0 AND at_risk_value >= 0",
            name="values_non_negative",
        ),
        # The ordering invariant, enforced in the database as well as in the domain
        # model: at-risk cannot exceed weighted, weighted cannot exceed pipeline.
        sa.CheckConstraint(
            "weighted_value <= pipeline_value AND at_risk_value <= weighted_value",
            name="values_ordered",
        ),
    )


class Intervention(Base, CreatedAtMixin):
    """Drafted by a model; ranked by `analytics/` (rule 9)."""

    __tablename__ = "interventions"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    rank: Mapped[int] = mapped_column(sa.Integer)
    title: Mapped[short_text]
    # `ProposedAction`, not `ActionType`: an intervention records what was *proposed*,
    # including proposals the policy layer refused. See migration 0004.
    action_type: Mapped[ProposedAction] = mapped_column(pg_enum(ProposedAction, "proposed_action"))
    rationale: Mapped[long_text]
    expected_value: Mapped[money]
    effort_score: Mapped[score]
    risk_score: Mapped[score]
    composite_score: Mapped[score]

    __table_args__ = (
        sa.UniqueConstraint("run_id", "rank", name="uq_interventions_run_id_rank"),
        sa.CheckConstraint("rank >= 1", name="rank_positive"),
        sa.CheckConstraint("expected_value >= 0", name="expected_value_non_negative"),
    )
