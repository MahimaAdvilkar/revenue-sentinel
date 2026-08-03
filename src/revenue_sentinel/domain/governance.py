"""Policy decisions, approval requests, and action records.

The chain is deliberate and complete: an intervention gets exactly one
`PolicyEvaluation`; an evaluation that returns `REQUIRE_APPROVAL` produces an
`ApprovalRequest`; and every `ActionRecord` names the evaluation or approval that
authorized it. There is no way to represent an action that nothing authorized.

`ActionRecord.idempotency_key` is UNIQUE in the database. Duplicate execution is
prevented by the constraint, not by application logic, because the constraint is the
only place it can be prevented reliably.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.base import (
    Digest,
    DomainModel,
    NonEmptyStr,
    UtcDatetime,
)
from revenue_sentinel.domain.enums import (
    ActionStatus,
    ActionType,
    ApprovalStatus,
    PolicyDecision,
    RiskTier,
)

DECIDED_APPROVAL_STATUSES = frozenset({ApprovalStatus.APPROVED, ApprovalStatus.REJECTED})
"""Statuses that require a decider and a decision timestamp. `EXPIRED` does not --
nobody decided anything; the window simply elapsed."""


class PolicyEvaluation(DomainModel):
    """One deterministic decision about one intervention.

    `matched_rules` and `reason` are recorded so a decision can be explained to a
    human without re-running the engine (ADR-0005).
    """

    id: UUID
    intervention_id: UUID
    policy_version: NonEmptyStr
    risk_tier: RiskTier
    decision: PolicyDecision
    matched_rules: tuple[str, ...]
    reason: NonEmptyStr
    evaluated_at: UtcDatetime

    @model_validator(mode="after")
    def _decision_is_explained(self) -> PolicyEvaluation:
        if not self.matched_rules:
            raise ValueError("a policy decision must name at least one matched rule")
        return self


class ApprovalRequest(DomainModel):
    """A pending or resolved request for human authorization."""

    id: UUID
    policy_evaluation_id: UUID
    run_id: UUID
    status: ApprovalStatus
    requested_at: UtcDatetime
    expires_at: UtcDatetime
    decided_at: UtcDatetime | None = None
    decided_by: str | None = None
    decision_note: str | None = None

    @model_validator(mode="after")
    def _decision_fields_are_consistent(self) -> ApprovalRequest:
        if self.expires_at <= self.requested_at:
            raise ValueError("expires_at must be after requested_at")
        decided = self.status in DECIDED_APPROVAL_STATUSES
        if decided and (self.decided_at is None or self.decided_by is None):
            raise ValueError(f"status {self.status} requires decided_at and decided_by")
        if not decided and (self.decided_at is not None or self.decided_by is not None):
            raise ValueError(f"status {self.status} must not carry a decider")
        return self


class ActionRecord(DomainModel):
    """An external effect: attempted, succeeded, or failed -- always authorized.

    `authorized_by` points at the `PolicyEvaluation` that allowed the action or the
    `ApprovalRequest` that approved it. It is not optional.
    """

    id: UUID
    run_id: UUID
    intervention_id: UUID
    action_type: ActionType
    # Stored, not just hashed: `idempotency_key = sha256(run_id | intervention_ref |
    # action_type | target_ref)`, and a key nobody can recompute is a key nobody can
    # audit. Keeping the input alongside the digest makes the constraint checkable.
    target_ref: NonEmptyStr
    idempotency_key: Digest
    status: ActionStatus
    authorized_by: UUID
    attempt_count: int = Field(ge=0)
    result: JSONObject | None = None
    executed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _terminal_status_has_an_outcome(self) -> ActionRecord:
        if self.status is ActionStatus.SUCCEEDED and self.executed_at is None:
            raise ValueError("a succeeded action requires executed_at")
        if self.status is ActionStatus.PENDING and self.attempt_count != 0:
            raise ValueError("a pending action has not been attempted")
        return self
