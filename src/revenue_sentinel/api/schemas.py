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
    opportunity_ref: str | None


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
