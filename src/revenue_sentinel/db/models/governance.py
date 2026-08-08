"""Policy evaluations, approval requests, and action records.

`action_records.idempotency_key` is UNIQUE. Duplicate execution is prevented by the
database, which is the only place it can be prevented reliably -- an application
check loses the race the moment two workers replay the same run concurrently.

`risk_tier` is `SMALLINT` with a range check rather than a native enum, because
escalation is an ordering operation (`max(tier_a, tier_b)`) and PostgreSQL enums do
not order the way the policy engine needs. This is the one documented deviation from
"enums are native" in `docs/data-model.md` §1.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from revenue_sentinel.core.types import JSONValue
from revenue_sentinel.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    digest,
    json_object,
    long_text,
    pg_enum,
    short_text,
    timestamp_tz,
    uuid_fk,
    uuid_pk,
)
from revenue_sentinel.domain.enums import (
    ActionStatus,
    ActionType,
    ApprovalStatus,
    PolicyDecision,
)


class PolicyEvaluation(Base, CreatedAtMixin):
    __tablename__ = "policy_evaluations"

    id: Mapped[uuid_pk]
    intervention_id: Mapped[uuid_fk] = mapped_column(
        sa.ForeignKey("interventions.id", ondelete="CASCADE"), unique=True
    )
    policy_version: Mapped[str] = mapped_column(sa.String(16))
    risk_tier: Mapped[int] = mapped_column(sa.SmallInteger)
    decision: Mapped[PolicyDecision] = mapped_column(pg_enum(PolicyDecision, "policy_decision"))
    matched_rules: Mapped[list[JSONValue]] = mapped_column(JSONB, default=list)
    reason: Mapped[long_text]
    evaluated_at: Mapped[timestamp_tz]

    __table_args__ = (
        sa.CheckConstraint("risk_tier >= 0 AND risk_tier <= 3", name="risk_tier_in_range"),
        sa.Index("ix_policy_evaluations_decision", "decision"),
    )


class ApprovalRequest(Base, TimestampMixin):
    __tablename__ = "approval_requests"

    id: Mapped[uuid_pk]
    policy_evaluation_id: Mapped[uuid_fk] = mapped_column(
        sa.ForeignKey("policy_evaluations.id", ondelete="CASCADE"), unique=True
    )
    run_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    approval_ref: Mapped[str] = mapped_column(sa.String(16), unique=True, index=True)
    status: Mapped[ApprovalStatus] = mapped_column(pg_enum(ApprovalStatus, "approval_status"))
    requested_by: Mapped[short_text]
    """The actor that asked. A real column as of migration 0005 -- it was previously
    smuggled into `decision_note` as `requested_by=<actor>` and parsed back out, which
    worked but put an authorisation-relevant value in a free-text field that any later
    note would overwrite. Self-approval prevention compares against this."""

    requested_at: Mapped[timestamp_tz]
    expires_at: Mapped[timestamp_tz]
    decided_at: Mapped[timestamp_tz | None] = mapped_column(nullable=True)
    decided_by: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (
        sa.CheckConstraint("expires_at > requested_at", name="expiry_after_request"),
        sa.Index("ix_approval_requests_status_expires_at", "status", "expires_at"),
    )


class ActionRecord(Base, TimestampMixin):
    """Every action traces to the policy decision or approval that authorized it."""

    __tablename__ = "action_records"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    intervention_id: Mapped[uuid_fk] = mapped_column(
        sa.ForeignKey("interventions.id", ondelete="CASCADE")
    )
    action_type: Mapped[ActionType] = mapped_column(pg_enum(ActionType, "action_type"))
    """`ActionType`, not `ProposedAction`. The executable vocabulary has no tier-3
    member, so a prohibited action has no representation in this table at all -- the
    first and cheapest of the four things that make Tier 3 unexecutable."""

    idempotency_key: Mapped[digest] = mapped_column(unique=True)
    status: Mapped[ActionStatus] = mapped_column(pg_enum(ActionStatus, "action_status"))
    authorized_by: Mapped[uuid_fk] = mapped_column(
        sa.ForeignKey("policy_evaluations.id", ondelete="RESTRICT")
    )
    """The decision that permitted this. A real foreign key as of migration 0006: the
    docstring above claimed every action traces to its authorisation, and a claim like
    that belongs in the schema rather than in a comment."""

    approval_request_id: Mapped[uuid_fk | None] = mapped_column(
        sa.ForeignKey("approval_requests.id", ondelete="RESTRICT"), nullable=True
    )
    """Set only for actions that needed a person. `NULL` for Tier 1, which is how a
    query can tell auto-approved work from approved work without re-deriving tiers."""

    attempt_count: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("0"))
    result: Mapped[json_object | None] = mapped_column(JSONB, nullable=True)
    executed_at: Mapped[timestamp_tz | None] = mapped_column(nullable=True)
    target_ref: Mapped[short_text]

    __table_args__ = (
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        sa.Index("ix_action_records_run_id_status", "run_id", "status"),
    )
