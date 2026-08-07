"""Closed vocabularies.

Each of these mirrors a native PostgreSQL enum type of the same (snake_case) name,
per `docs/data-model.md` §1. Values are snake_case rather than display text --
`mid_market`, not `Mid-Market` -- because the stored value is an identifier and
presentation is a UI concern. Changing a display label should not require a
migration.

`RiskTier` is the one deliberate exception: it is an `IntEnum` backed by a
`SMALLINT` column with a range check, not a native enum, because tier escalation is
an ordering operation (`max(tier_a, tier_b)`) and string enums do not order.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum, unique
from typing import Final


# ---------------------------------------------------------------------------
# GTM source mirror
# ---------------------------------------------------------------------------
@unique
class AccountSegment(StrEnum):
    ENTERPRISE = "enterprise"
    MID_MARKET = "mid_market"
    SMB = "smb"


@unique
class OpportunityStage(StrEnum):
    DISCOVERY = "discovery"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


OPEN_STAGES: Final[frozenset[OpportunityStage]] = frozenset(
    {
        OpportunityStage.DISCOVERY,
        OpportunityStage.PROPOSAL,
        OpportunityStage.NEGOTIATION,
    }
)
"""Stages a detector may fire on. Closed opportunities cannot stall."""


@unique
class ActivityType(StrEnum):
    EMAIL = "email"
    CALL = "call"
    MEETING = "meeting"
    NOTE = "note"


@unique
class ActivityDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


SALES_TOUCH_TYPES: Final[frozenset[ActivityType]] = frozenset(
    {ActivityType.EMAIL, ActivityType.CALL, ActivityType.MEETING}
)
"""What counts as a sales touch for the inactivity window. A `note` is a rep
talking to themselves, not to the buyer, so it does not reset the clock."""


@unique
class EngagementChannel(StrEnum):
    EMAIL = "email"
    CALENDAR = "calendar"
    WEB = "web"


@unique
class EngagementEventType(StrEnum):
    SENT = "sent"
    OPENED = "opened"
    CLICKED = "clicked"
    MEETING_HELD = "meeting_held"


@unique
class SupportSeverity(StrEnum):
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"
    P4 = "p4"


@unique
class SupportStatus(StrEnum):
    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


# ---------------------------------------------------------------------------
# Events and signals
# ---------------------------------------------------------------------------
@unique
class SourceSystem(StrEnum):
    CRM = "crm"
    PRODUCT = "product"
    ENGAGEMENT = "engagement"
    SUPPORT = "support"
    ENRICHMENT = "enrichment"


@unique
class EventType(StrEnum):
    """Canonical event types. The first six are emitted in v1; the rest are
    declared contracts for future scenarios and are never produced yet."""

    CRM_OPPORTUNITY_UPDATED = "crm.opportunity.updated"
    CRM_ACTIVITY_LOGGED = "crm.activity.logged"
    PRODUCT_USAGE_ROLLUP = "product.usage.rollup"
    ENGAGEMENT_EMAIL_ACTIVITY = "engagement.email.activity"
    ENGAGEMENT_MEETING_HELD = "engagement.meeting.held"
    SUPPORT_ISSUE_OPENED = "support.issue.opened"

    # Declared, not emitted in v1.
    CRM_OPPORTUNITY_STAGE_CHANGED = "crm.opportunity.stage_changed"
    CRM_RECORD_QUALITY_FLAGGED = "crm.record.quality_flagged"
    ENRICHMENT_PROVIDER_USAGE_REPORTED = "enrichment.provider.usage_reported"
    CAMPAIGN_PERFORMANCE_ROLLUP = "campaign.performance.rollup"


EMITTED_EVENT_TYPES: Final[frozenset[EventType]] = frozenset(
    {
        EventType.CRM_OPPORTUNITY_UPDATED,
        EventType.CRM_ACTIVITY_LOGGED,
        EventType.PRODUCT_USAGE_ROLLUP,
        EventType.ENGAGEMENT_EMAIL_ACTIVITY,
        EventType.ENGAGEMENT_MEETING_HELD,
        EventType.SUPPORT_ISSUE_OPENED,
    }
)
"""The six event types v1 actually produces. The other four are contracts only."""


@unique
class TrustLevel(StrEnum):
    """Single-member by design.

    There is no code path that marks ingested GTM content as trusted (rule 14).
    This is an enum rather than a constant so the database column carries the same
    guarantee the Python type does.
    """

    UNTRUSTED = "untrusted"


@unique
class SignalType(StrEnum):
    """Only `STALLED_OPPORTUNITY` has a detector in v1; the rest are ROADMAP
    registry entries with declared parameters and no implementation."""

    STALLED_OPPORTUNITY = "stalled_opportunity"
    RENEWAL_RISK = "renewal_risk"
    DEAL_SLIPPAGE = "deal_slippage"
    PQA_DISCOVERY = "pqa_discovery"
    ACCOUNT_EXPANSION = "account_expansion"
    CRM_DATA_QUALITY = "crm_data_quality"
    ENRICHMENT_COST_ANOMALY = "enrichment_cost_anomaly"
    CAMPAIGN_UNDERPERFORMANCE = "campaign_underperformance"


IMPLEMENTED_SIGNAL_TYPES: Final[frozenset[SignalType]] = frozenset({SignalType.STALLED_OPPORTUNITY})
"""Signal types with a real detector behind them. Everything else is ROADMAP."""


@unique
class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Incidents and workflow
# ---------------------------------------------------------------------------
@unique
class IncidentType(StrEnum):
    """Kept separate from `SignalType` even though v1's vocabularies coincide: an
    incident is a unit of work, and more than one signal type may eventually open
    the same kind of incident."""

    STALLED_OPPORTUNITY = "stalled_opportunity"
    RENEWAL_RISK = "renewal_risk"
    DEAL_SLIPPAGE = "deal_slippage"
    PQA_DISCOVERY = "pqa_discovery"
    ACCOUNT_EXPANSION = "account_expansion"
    CRM_DATA_QUALITY = "crm_data_quality"
    ENRICHMENT_COST_ANOMALY = "enrichment_cost_anomaly"
    CAMPAIGN_UNDERPERFORMANCE = "campaign_underperformance"


@unique
class IncidentStatus(StrEnum):
    """The lifecycle in `docs/event-model.md` §5.

    The legal-transition map lives in `incidents/` and arrives in Session 2; this
    enum and `TERMINAL_INCIDENT_STATUSES` are the vocabulary only.
    """

    DETECTED = "detected"
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    ANALYZED = "analyzed"
    STRATEGIZED = "strategized"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    CLOSED_REJECTED = "closed_rejected"
    EXPIRED = "expired"
    DISMISSED = "dismissed"
    FAILED = "failed"


TERMINAL_INCIDENT_STATUSES: Final[frozenset[IncidentStatus]] = frozenset(
    {
        IncidentStatus.COMPLETED,
        IncidentStatus.CLOSED_REJECTED,
        IncidentStatus.EXPIRED,
        IncidentStatus.DISMISSED,
        IncidentStatus.FAILED,
    }
)


@unique
class WorkflowStatus(StrEnum):
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"


@unique
class ComputedBy(StrEnum):
    """Provenance of a numeric figure.

    `impact_assessments.computed_by` is always `DETERMINISTIC`. The `MODEL` member
    exists so that a violation of rule 9 would be *representable and therefore
    detectable* by the evaluation suite, not so that it is permitted.
    """

    DETERMINISTIC = "deterministic"
    MODEL = "model"


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------
@unique
class RiskTier(IntEnum):
    """Risk tiers from `docs/security-model.md` §3.

    Integer-valued so escalation is `max()`. When classification is ambiguous the
    engine takes the higher tier -- caution is coded, not hoped for.
    """

    READ_OR_COMPUTE = 0
    INTERNAL_REVERSIBLE = 1
    CUSTOMER_FACING_OR_MATERIAL = 2
    PROHIBITED = 3


@unique
class PolicyDecision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@unique
class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@unique
class ActionType(StrEnum):
    """What the system is *able to execute*. Stored on `action_records`.

    Deliberately narrower than `ProposedAction`: there is no member here for anything
    the policy layer would refuse, so a prohibited action has no representation in the
    execution tables at all.
    """

    CRM_TASK = "crm_task"
    EMAIL_DRAFT = "email_draft"
    CRM_FIELD_UPDATE = "crm_field_update"
    SLACK_APPROVAL_REQUEST = "slack_approval_request"


@unique
class ProposedAction(StrEnum):
    """What a strategy agent may *propose*. Stored on `interventions`.

    Wider than `ActionType` on purpose. A system that can only represent permissible
    proposals cannot record having refused an impermissible one -- the refusal would
    have to be dropped on the floor, and a denial nobody can point at is
    indistinguishable from a denial that never happened.

    So the model is free to propose sending an email directly. It is simply told no,
    in writing, with the rule that said so (`governance/tiers.py`).
    """

    CRM_TASK = "crm_task"
    EMAIL_DRAFT = "email_draft"
    CRM_FIELD_UPDATE = "crm_field_update"
    SLACK_APPROVAL_REQUEST = "slack_approval_request"

    # Tier 3 -- proposable, never executable.
    SEND_EMAIL_DIRECT = "send_email_direct"
    RECORD_DELETE = "record_delete"


EXECUTABLE_ACTIONS: Final = frozenset(ActionType)
"""The `ProposedAction` members that have an `ActionType` counterpart. Compared by
value, since the two enums overlap by value rather than by identity."""


@unique
class ActionStatus(StrEnum):
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Cost and observability
# ---------------------------------------------------------------------------
@unique
class ToolCallStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"


@unique
class CostType(StrEnum):
    MODEL_INFERENCE = "model_inference"
    TOOL_INVOCATION = "tool_invocation"


@unique
class BudgetScope(StrEnum):
    GLOBAL = "global"
    INCIDENT = "incident"
    RUN = "run"


@unique
class BudgetPeriod(StrEnum):
    RUN = "run"
    INCIDENT = "incident"
    MONTHLY = "monthly"


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
@unique
class EvaluationOutcome(StrEnum):
    """Past-participle values (`passed`, not `pass`) so the member name does not
    collide with `bandit`'s hardcoded-password heuristic on `PASS = "..."`. The
    alternative was a blanket `S105` suppression on this file, which would have
    silenced a real finding elsewhere in it later."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
