"""Incidents -- the unit of work.

One signal opens one incident. The lifecycle is in `docs/event-model.md` §5; the
legal-transition map and the state machine that enforces it arrive in Session 2.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import model_validator

from revenue_sentinel.domain.base import (
    DomainModel,
    IncidentRef,
    NonEmptyStr,
    UtcDatetime,
)
from revenue_sentinel.domain.enums import (
    TERMINAL_INCIDENT_STATUSES,
    IncidentStatus,
    IncidentType,
    Severity,
)


class Incident(DomainModel):
    """An open or closed piece of revenue work."""

    id: UUID
    incident_ref: IncidentRef
    signal_id: UUID
    incident_type: IncidentType
    status: IncidentStatus
    severity: Severity
    account_id: UUID
    opportunity_id: UUID | None = None
    opened_at: UtcDatetime
    closed_at: UtcDatetime | None = None
    title: NonEmptyStr

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_INCIDENT_STATUSES

    @model_validator(mode="after")
    def _closure_matches_status(self) -> Incident:
        """A closed incident has a closing timestamp, and an open one does not.

        Enforced here because an incident that reads as open in the queue while
        carrying a `closed_at` is the kind of inconsistency that survives review.
        """
        if self.status in TERMINAL_INCIDENT_STATUSES and self.closed_at is None:
            raise ValueError(f"incident in terminal status {self.status} requires closed_at")
        if self.status not in TERMINAL_INCIDENT_STATUSES and self.closed_at is not None:
            raise ValueError(
                f"incident in non-terminal status {self.status} must not set closed_at"
            )
        if self.closed_at is not None and self.closed_at < self.opened_at:
            raise ValueError("closed_at precedes opened_at")
        return self
