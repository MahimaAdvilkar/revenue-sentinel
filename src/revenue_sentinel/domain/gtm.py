"""The GTM source mirror -- local, SIMULATED copies of CRM, product, engagement,
support, and enrichment records.

**Every model here carries `is_simulated`, which is `True` for all v1 data.** The
dashboard renders its SIMULATED badge from this field rather than from a hardcoded
string, so the honesty of the UI is a property of the data (rule 5).

Free-text fields on these models (`Activity.subject`, `Activity.body`,
`SupportIssue.summary`) are **untrusted** (rule 14). They originate outside the
system, they may be adversarial, and they are never concatenated into a prompt --
they travel inside delimited evidence blocks only.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.base import (
    AccountRef,
    CurrencyCode,
    DomainModel,
    Money,
    NonEmptyStr,
    OpportunityRef,
    Probability,
    Score,
    UserRef,
    UtcDatetime,
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


class Account(DomainModel):
    """A customer account."""

    id: UUID
    account_ref: AccountRef
    name: NonEmptyStr
    segment: AccountSegment
    industry: NonEmptyStr
    employee_count: int = Field(ge=0)
    owner_id: UserRef
    is_simulated: bool = True
    created_at: UtcDatetime
    updated_at: UtcDatetime


class Opportunity(DomainModel):
    """A sales opportunity. `amount` is the figure the impact calculation starts from."""

    id: UUID
    opportunity_ref: OpportunityRef
    account_id: UUID
    name: NonEmptyStr
    stage: OpportunityStage
    amount: Money
    currency: CurrencyCode
    expected_close_date: date
    probability: Probability
    owner_id: UserRef
    is_simulated: bool = True
    created_at: UtcDatetime
    updated_at: UtcDatetime


class Activity(DomainModel):
    """A logged sales touch. `subject` and `body` are untrusted content."""

    id: UUID
    account_id: UUID
    opportunity_id: UUID | None = None
    activity_type: ActivityType
    direction: ActivityDirection
    occurred_at: UtcDatetime
    subject: str
    body: str
    is_simulated: bool = True
    created_at: UtcDatetime


class UsageSnapshot(DomainModel):
    """A weekly product-usage rollup. Week-over-week growth in `feature_events` is
    one half of the stalled-opportunity conjunction."""

    id: UUID
    account_id: UUID
    period_start: date
    period_end: date
    active_users: int = Field(ge=0)
    sessions: int = Field(ge=0)
    feature_events: int = Field(ge=0)
    usage_score: Score
    is_simulated: bool = True
    created_at: UtcDatetime


class EngagementEvent(DomainModel):
    """An email open, click, send, or held meeting."""

    id: UUID
    account_id: UUID
    channel: EngagementChannel
    event_type: EngagementEventType
    occurred_at: UtcDatetime
    is_simulated: bool = True
    created_at: UtcDatetime


class SupportIssue(DomainModel):
    """A support ticket. `summary` is untrusted content."""

    id: UUID
    account_id: UUID
    external_ref: NonEmptyStr
    severity: SupportSeverity
    status: SupportStatus
    opened_at: UtcDatetime
    summary: str
    is_simulated: bool = True
    created_at: UtcDatetime


class CompanyProfile(DomainModel):
    """Firmographic enrichment for an account."""

    id: UUID
    account_id: UUID
    hq_country: NonEmptyStr
    revenue_band: NonEmptyStr
    tech_stack: JSONObject
    enriched_at: UtcDatetime
    source: NonEmptyStr
    is_simulated: bool = True
    created_at: UtcDatetime
