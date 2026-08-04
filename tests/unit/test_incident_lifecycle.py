"""The incident state machine.

Encodes `docs/event-model.md` §5. The tests check the map against the diagram in
both directions: every documented edge exists, and every edge that exists is
documented -- so a stray transition added later fails here rather than shipping.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from revenue_sentinel.domain.enums import TERMINAL_INCIDENT_STATUSES, IncidentStatus
from revenue_sentinel.incidents.lifecycle import (
    LEGAL_TRANSITIONS,
    IllegalTransitionError,
    is_legal,
    is_terminal,
    require_legal,
)

S = IncidentStatus

# Transcribed from the state diagram in docs/event-model.md §5.
DOCUMENTED_EDGES = {
    (S.DETECTED, S.TRIAGED),
    (S.DETECTED, S.DISMISSED),
    (S.TRIAGED, S.INVESTIGATING),
    (S.TRIAGED, S.DISMISSED),
    (S.INVESTIGATING, S.ANALYZED),
    (S.INVESTIGATING, S.FAILED),
    (S.ANALYZED, S.STRATEGIZED),
    (S.ANALYZED, S.FAILED),
    (S.STRATEGIZED, S.AWAITING_APPROVAL),
    (S.STRATEGIZED, S.EXECUTING),
    (S.AWAITING_APPROVAL, S.EXECUTING),
    (S.AWAITING_APPROVAL, S.CLOSED_REJECTED),
    (S.AWAITING_APPROVAL, S.EXPIRED),
    (S.EXECUTING, S.COMPLETED),
}


@pytest.mark.parametrize(("source", "target"), sorted(DOCUMENTED_EDGES, key=str))
def test_every_documented_edge_is_legal(source: IncidentStatus, target: IncidentStatus) -> None:
    assert is_legal(source, target)


def test_no_undocumented_edge_exists() -> None:
    """The map cannot grow past the diagram without this failing."""
    actual = {
        (source, target) for source, targets in LEGAL_TRANSITIONS.items() for target in targets
    }
    assert actual == DOCUMENTED_EDGES


def test_every_status_has_an_entry() -> None:
    """A missing key would raise `KeyError` at runtime instead of rejecting cleanly."""
    assert set(LEGAL_TRANSITIONS) == set(IncidentStatus)


@pytest.mark.parametrize("status", sorted(TERMINAL_INCIDENT_STATUSES, key=str))
def test_terminal_states_have_no_outgoing_edges(status: IncidentStatus) -> None:
    """An incident cannot be reopened, so a closed audit trail cannot grow later."""
    assert LEGAL_TRANSITIONS[status] == frozenset()
    assert is_terminal(status)


@pytest.mark.parametrize("status", sorted(TERMINAL_INCIDENT_STATUSES, key=str))
def test_nothing_transitions_out_of_a_terminal_state(status: IncidentStatus) -> None:
    for target in IncidentStatus:
        assert not is_legal(status, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (S.DETECTED, S.EXECUTING),  # cannot skip investigation
        (S.DETECTED, S.COMPLETED),  # cannot skip everything
        (S.TRIAGED, S.ANALYZED),  # cannot skip investigating
        (S.INVESTIGATING, S.STRATEGIZED),  # cannot skip analysis
        (S.STRATEGIZED, S.COMPLETED),  # cannot execute without executing
        (S.EXECUTING, S.AWAITING_APPROVAL),  # approval precedes execution
        (S.COMPLETED, S.INVESTIGATING),  # no reopening
        (S.DISMISSED, S.TRIAGED),  # no reopening
    ],
)
def test_illegal_transitions_are_rejected(source: IncidentStatus, target: IncidentStatus) -> None:
    assert not is_legal(source, target)
    with pytest.raises(IllegalTransitionError):
        require_legal("INC-001", source, target)


def test_a_status_cannot_transition_to_itself() -> None:
    for status in IncidentStatus:
        assert not is_legal(status, status)


def test_require_legal_permits_a_documented_edge() -> None:
    require_legal("INC-001", S.DETECTED, S.TRIAGED)


def test_the_error_names_what_was_allowed() -> None:
    """An error that only says "no" makes the caller guess."""
    with pytest.raises(IllegalTransitionError) as caught:
        require_legal("INC-001", S.DETECTED, S.COMPLETED)

    message = str(caught.value)
    assert "INC-001" in message
    assert "detected" in message
    assert "completed" in message
    assert "triaged" in message  # what would have been legal


def test_the_error_explains_terminality() -> None:
    with pytest.raises(IllegalTransitionError, match="terminal"):
        require_legal("INC-001", S.COMPLETED, S.EXECUTING)


def test_the_error_carries_structured_fields() -> None:
    with pytest.raises(IllegalTransitionError) as caught:
        require_legal("INC-002", S.DETECTED, S.COMPLETED)

    assert caught.value.incident_ref == "INC-002"
    assert caught.value.from_status is S.DETECTED
    assert caught.value.to_status is S.COMPLETED


def test_the_happy_path_walks_end_to_end() -> None:
    """Detected through completed, one legal edge at a time."""
    path = [
        S.DETECTED,
        S.TRIAGED,
        S.INVESTIGATING,
        S.ANALYZED,
        S.STRATEGIZED,
        S.AWAITING_APPROVAL,
        S.EXECUTING,
        S.COMPLETED,
    ]
    for source, target in pairwise(path):
        require_legal("INC-001", source, target)


def test_non_terminal_states_are_not_terminal() -> None:
    for status in set(IncidentStatus) - TERMINAL_INCIDENT_STATUSES:
        assert not is_terminal(status)
