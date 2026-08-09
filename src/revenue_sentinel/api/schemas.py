"""HTTP response models.

Separate from `domain/` on purpose. Domain models are internal and free to change;
these are the wire contract the Session 9 dashboard generates TypeScript types
from, and coupling the two would make an internal refactor a breaking API change.

Every response carrying GTM data exposes `is_simulated`. The dashboard renders its
SIMULATED badge from that field rather than from a hardcoded string, so the
honesty of the UI is a property of the payload (rule 5).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from revenue_sentinel.domain.enums import (
    IncidentStatus,
    IncidentType,
    OpportunityStage,
    Severity,
    SignalType,
)


class ApiModel(BaseModel):
    """Base for every wire model: immutable and closed."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)


class SignalSummary(ApiModel):
    """The signal that produced an incident."""

    signal_type: SignalType
    detector_version: str
    severity: Severity
    detected_at: datetime
    dedupe_key: str
    evidence_event_count: int


class OpportunitySummary(ApiModel):
    opportunity_ref: str
    name: str
    stage: OpportunityStage
    amount: Decimal
    currency: str
    probability: Decimal
    expected_close_date: str
    is_simulated: bool


class AccountSummary(ApiModel):
    account_ref: str
    name: str
    segment: str
    is_simulated: bool


class IncidentSummary(ApiModel):
    """One row in the incident queue."""

    incident_ref: str
    incident_type: IncidentType
    status: IncidentStatus
    severity: Severity
    title: str
    opened_at: datetime
    closed_at: datetime | None
    account_ref: str
    account_name: str
    opportunity_ref: str | None

    # Added in Session 9 for the incident queue, which has to rank by money and could not
    # do so from refs alone. All read-only, all nullable where the underlying row may not
    # exist yet: an incident that has not been investigated has no impact assessment, and
    # saying so with `null` beats omitting the column and leaving the UI to guess.
    amount: str | None
    currency: str | None
    at_risk_value: str | None
    is_simulated: bool
    """`True` for every row in v1. Read from `accounts.is_simulated` rather than
    hardcoded, so the badge stops appearing if a real integration ever lands (rule 5)."""


class IncidentDetail(ApiModel):
    """One incident with the signal and records it concerns."""

    incident_ref: str
    incident_type: IncidentType
    status: IncidentStatus
    severity: Severity
    title: str
    opened_at: datetime
    closed_at: datetime | None
    account: AccountSummary
    opportunity: OpportunitySummary | None
    signal: SignalSummary


class IncidentListResponse(ApiModel):
    count: int
    incidents: tuple[IncidentSummary, ...]


class IngestResponse(ApiModel):
    """The outcome of one ingestion cycle.

    `ingestion_status` is always `SIMULATED` in v1 and is returned on every
    response so a caller cannot mistake this for a real source feed.
    """

    ingestion_status: str
    evaluated_at: datetime
    raw_events_offered: int
    raw_events_inserted: int
    events_normalized: int
    opportunities_evaluated: int
    signals_created: int
    signals_deduplicated: int
    incidents_opened: int
    incident_refs: tuple[str, ...]


class ErrorResponse(ApiModel):
    detail: str
    resource: str | None = None
    ref: str | None = None


# ---------------------------------------------------------------------------
# Dashboard read models (Session 9)
# ---------------------------------------------------------------------------
# Money and cost are **strings**, deliberately. JSON numbers are IEEE floats and cannot
# carry a `Decimal` faithfully; serialising `0.000000` as `0.0` would undo the reason
# `cost_entries.amount_usd` has six decimal places. The frontend formats a string it can
# trust rather than a float it cannot.
FreeFormJson = dict[str, Any]
"""Evidence content, as the API publishes it.

Internally this is `JSONObject`, whose value type is **recursive**. FastAPI emits that
faithfully as a self-referential `$ref`, and `openapi-typescript` then generates a
recursive type alias that TypeScript refuses to resolve through indexed access
(`TS2502`).

The boundary is the right place to stop the recursion. A client rendering evidence
key-by-key does not depend on the nesting rules, and publishing a free-form object
(`additionalProperties: true`) is both a truthful description of the payload and one a
generator can express. The internal type is unchanged; only what the contract promises
is narrowed.
"""


class EvidenceItemView(BaseModel):
    evidence_ref: str
    source_system: str
    tool_name: str
    trust_level: str
    content: FreeFormJson
    integration_status: str


class HypothesisView(BaseModel):
    hypothesis_ref: str
    statement: str
    confidence: str
    rank: int
    cites: list[str]


class ImpactView(BaseModel):
    pipeline_value: str
    weighted_value: str
    at_risk_value: str
    currency: str
    computed_by: str
    method_version: str


class InvestigationResponse(BaseModel):
    incident_ref: str
    evidence: list[EvidenceItemView]
    hypotheses: list[HypothesisView]
    impact: ImpactView | None


class InterventionView(BaseModel):
    rank: int
    title: str
    action_type: str
    rationale: str
    target_ref: str
    expected_value: str
    composite_score: str
    decision: str | None
    risk_tier: int | None
    matched_rules: list[str]
    reason: str | None
    executed: bool
    action_status: str | None
    integration_status: str


class TimelineEventView(BaseModel):
    occurred_at: datetime
    source: str
    event_type: str
    detail: str
    trace_id: str | None
    span_id: str | None
    parent_span_id: str | None
    amount_usd: str | None
    pricing_version: str | None
    integration_status: str | None


class TimelineResponse(BaseModel):
    incident_ref: str
    trace_count: int
    events: list[TimelineEventView]


class CostLedgerEntry(BaseModel):
    kind: str
    cost_type: str
    amount_usd: str
    pricing_version: str


class CostSummaryResponse(BaseModel):
    incident_ref: str
    model_cost: str
    tool_cost: str
    total_cost: str
    model_calls: int
    tool_calls: int
    pricing_versions: list[str]
    concurrency_note: str
    ledger: list[CostLedgerEntry]


class ApprovalInboxItem(BaseModel):
    approval_ref: str
    status: str
    requested_by: str
    expires_at: datetime
    intervention_title: str
    approve_command: str
    integration_status: str


class ApprovalInboxResponse(BaseModel):
    pending: list[ApprovalInboxItem]
    identity_note: str


class EvaluationResultItem(BaseModel):
    check_name: str
    outcome: str
    expected: str
    actual: str
    detail: str | None


class EvaluationResponse(BaseModel):
    suite_name: str
    evaluator_version: str
    passed: int
    total: int
    llm_judge_used: bool
    evaluation_cost: str
    results: list[EvaluationResultItem]


class OverviewResponse(BaseModel):
    total_at_risk: str
    total_weighted: str
    open_incidents: int
    incidents_by_status: dict[str, int]
    integration_status: str
