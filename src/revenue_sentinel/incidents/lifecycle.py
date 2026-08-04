"""The incident state machine.

Encodes `docs/event-model.md` §5 as data. Every transition the diagram draws is
here, and nothing else is legal.

Two properties are enforced rather than assumed:

* **Terminal states are terminal.** `COMPLETED`, `CLOSED_REJECTED`, `EXPIRED`,
  `DISMISSED`, and `FAILED` have no outgoing edges. An incident cannot be reopened,
  which means the audit trail for a closed incident cannot grow after the fact.
* **No implicit transitions.** Moving an incident is a function call that either
  succeeds or raises. There is no "set status and hope", because status is the
  field a dashboard renders and an approver acts on.
"""

from __future__ import annotations

from typing import Final

from revenue_sentinel.core.errors import RevenueSentinelError
from revenue_sentinel.domain.enums import TERMINAL_INCIDENT_STATUSES, IncidentStatus


class IllegalTransitionError(RevenueSentinelError):
    """An attempt to move an incident along an edge that does not exist."""

    def __init__(self, incident_ref: str, from_status: IncidentStatus, to: IncidentStatus) -> None:
        self.incident_ref = incident_ref
        self.from_status = from_status
        self.to_status = to
        allowed = sorted(status.value for status in LEGAL_TRANSITIONS[from_status])
        super().__init__(
            f"{incident_ref}: cannot move from {from_status.value} to {to.value}. "
            f"Legal from {from_status.value}: {allowed or 'nothing (terminal)'}"
        )


LEGAL_TRANSITIONS: Final[dict[IncidentStatus, frozenset[IncidentStatus]]] = {
    IncidentStatus.DETECTED: frozenset({IncidentStatus.TRIAGED, IncidentStatus.DISMISSED}),
    IncidentStatus.TRIAGED: frozenset({IncidentStatus.INVESTIGATING, IncidentStatus.DISMISSED}),
    IncidentStatus.INVESTIGATING: frozenset({IncidentStatus.ANALYZED, IncidentStatus.FAILED}),
    IncidentStatus.ANALYZED: frozenset({IncidentStatus.STRATEGIZED, IncidentStatus.FAILED}),
    IncidentStatus.STRATEGIZED: frozenset(
        {IncidentStatus.AWAITING_APPROVAL, IncidentStatus.EXECUTING}
    ),
    IncidentStatus.AWAITING_APPROVAL: frozenset(
        {
            IncidentStatus.EXECUTING,
            IncidentStatus.CLOSED_REJECTED,
            IncidentStatus.EXPIRED,
        }
    ),
    IncidentStatus.EXECUTING: frozenset({IncidentStatus.COMPLETED}),
    # Terminal states, spelled out rather than omitted so a missing key can never be
    # mistaken for an oversight.
    IncidentStatus.COMPLETED: frozenset(),
    IncidentStatus.CLOSED_REJECTED: frozenset(),
    IncidentStatus.EXPIRED: frozenset(),
    IncidentStatus.DISMISSED: frozenset(),
    IncidentStatus.FAILED: frozenset(),
}


def is_legal(from_status: IncidentStatus, to_status: IncidentStatus) -> bool:
    """Whether the edge exists."""
    return to_status in LEGAL_TRANSITIONS[from_status]


def require_legal(
    incident_ref: str, from_status: IncidentStatus, to_status: IncidentStatus
) -> None:
    """Raise `IllegalTransitionError` unless the edge exists."""
    if not is_legal(from_status, to_status):
        raise IllegalTransitionError(incident_ref, from_status, to_status)


def is_terminal(status: IncidentStatus) -> bool:
    return status in TERMINAL_INCIDENT_STATUSES
