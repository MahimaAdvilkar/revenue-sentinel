"""GTM source mirror tables -- local copies of what a real CRM, product analytics,
engagement, support, and enrichment system would return.

Every table here carries `is_simulated`, which is `True` for all v1 data (rule 5).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from revenue_sentinel.db.base import (
    Base,
    CreatedAtMixin,
    SimulatedMixin,
    TimestampMixin,
    calendar_date,
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
from revenue_sentinel.domain.enums import (
    AccountSegment,
    ActivityDirection,
    ActivityType,
    EngagementChannel,
    EngagementEventType,
    OpportunityStage,
    SupportSeverity,
    SupportStatus,
)


class Account(Base, TimestampMixin, SimulatedMixin):
    __tablename__ = "accounts"

    id: Mapped[uuid_pk]
    account_ref: Mapped[short_text] = mapped_column(unique=True, index=True)
    name: Mapped[short_text]
    segment: Mapped[AccountSegment] = mapped_column(pg_enum(AccountSegment, "account_segment"))
    industry: Mapped[short_text]
    employee_count: Mapped[int] = mapped_column(sa.Integer)
    owner_id: Mapped[short_text]

    __table_args__ = (
        sa.CheckConstraint("employee_count >= 0", name="employee_count_non_negative"),
    )


class Opportunity(Base, TimestampMixin, SimulatedMixin):
    __tablename__ = "opportunities"

    id: Mapped[uuid_pk]
    opportunity_ref: Mapped[short_text] = mapped_column(unique=True, index=True)
    account_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("accounts.id", ondelete="CASCADE"))
    name: Mapped[short_text]
    stage: Mapped[OpportunityStage] = mapped_column(pg_enum(OpportunityStage, "opportunity_stage"))
    amount: Mapped[money]
    currency: Mapped[str] = mapped_column(sa.String(3))
    expected_close_date: Mapped[calendar_date]
    probability: Mapped[probability]
    owner_id: Mapped[short_text]

    __table_args__ = (
        # Rule: guards nonsense figures. A negative pipeline amount is not a small
        # data-quality problem, it is a number that would corrupt every aggregate
        # downstream of it.
        sa.CheckConstraint("amount >= 0", name="amount_non_negative"),
        sa.CheckConstraint("probability >= 0 AND probability <= 1", name="probability_in_range"),
        sa.Index("ix_opportunities_account_id_stage", "account_id", "stage"),
    )


class Activity(Base, CreatedAtMixin, SimulatedMixin):
    """A logged sales touch. `subject` and `body` are untrusted content (rule 14)."""

    __tablename__ = "activities"

    id: Mapped[uuid_pk]
    account_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("accounts.id", ondelete="CASCADE"))
    opportunity_id: Mapped[uuid_fk | None] = mapped_column(
        sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=True
    )
    activity_type: Mapped[ActivityType] = mapped_column(pg_enum(ActivityType, "activity_type"))
    direction: Mapped[ActivityDirection] = mapped_column(
        pg_enum(ActivityDirection, "activity_direction")
    )
    occurred_at: Mapped[timestamp_tz]
    subject: Mapped[long_text]
    body: Mapped[long_text]

    __table_args__ = (
        # Powers "days since the most recent sales activity" as an index scan rather
        # than a table scan -- the detector's hottest query in Session 2.
        sa.Index("ix_activities_account_id_occurred_at", "account_id", "occurred_at"),
        sa.Index("ix_activities_opportunity_id_occurred_at", "opportunity_id", "occurred_at"),
    )


class UsageSnapshot(Base, CreatedAtMixin, SimulatedMixin):
    __tablename__ = "usage_snapshots"

    id: Mapped[uuid_pk]
    account_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("accounts.id", ondelete="CASCADE"))
    period_start: Mapped[calendar_date]
    period_end: Mapped[calendar_date]
    active_users: Mapped[int] = mapped_column(sa.Integer)
    sessions: Mapped[int] = mapped_column(sa.Integer)
    feature_events: Mapped[int] = mapped_column(sa.Integer)
    usage_score: Mapped[score]

    __table_args__ = (
        sa.UniqueConstraint("account_id", "period_start", name="uq_usage_snapshots_account_period"),
        sa.CheckConstraint("period_end >= period_start", name="period_ordered"),
        sa.CheckConstraint(
            "active_users >= 0 AND sessions >= 0 AND feature_events >= 0",
            name="counts_non_negative",
        ),
        sa.Index("ix_usage_snapshots_account_id_period_start", "account_id", "period_start"),
    )


class EngagementEvent(Base, CreatedAtMixin, SimulatedMixin):
    __tablename__ = "engagement_events"

    id: Mapped[uuid_pk]
    account_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("accounts.id", ondelete="CASCADE"))
    channel: Mapped[EngagementChannel] = mapped_column(
        pg_enum(EngagementChannel, "engagement_channel")
    )
    event_type: Mapped[EngagementEventType] = mapped_column(
        pg_enum(EngagementEventType, "engagement_event_type")
    )
    occurred_at: Mapped[timestamp_tz]

    __table_args__ = (
        sa.Index("ix_engagement_events_account_id_occurred_at", "account_id", "occurred_at"),
    )


class SupportIssue(Base, CreatedAtMixin, SimulatedMixin):
    """A support ticket. `summary` is untrusted content (rule 14)."""

    __tablename__ = "support_issues"

    id: Mapped[uuid_pk]
    account_id: Mapped[uuid_fk] = mapped_column(sa.ForeignKey("accounts.id", ondelete="CASCADE"))
    external_ref: Mapped[short_text] = mapped_column(unique=True)
    severity: Mapped[SupportSeverity] = mapped_column(pg_enum(SupportSeverity, "support_severity"))
    status: Mapped[SupportStatus] = mapped_column(pg_enum(SupportStatus, "support_status"))
    opened_at: Mapped[timestamp_tz]
    summary: Mapped[long_text]

    __table_args__ = (sa.Index("ix_support_issues_account_id_status", "account_id", "status"),)


class CompanyProfile(Base, CreatedAtMixin, SimulatedMixin):
    __tablename__ = "company_profiles"

    id: Mapped[uuid_pk]
    account_id: Mapped[uuid_fk] = mapped_column(
        sa.ForeignKey("accounts.id", ondelete="CASCADE"), unique=True
    )
    hq_country: Mapped[short_text]
    revenue_band: Mapped[short_text]
    tech_stack: Mapped[json_object]
    enriched_at: Mapped[timestamp_tz]
    source: Mapped[short_text]
