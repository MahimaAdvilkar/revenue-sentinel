"""Typed tool errors.

Seven codes, returned as structured tool results rather than raised as opaque
exceptions (`docs/mcp-design.md` §4). An agent receiving one gets a machine-readable
instruction about what to do next, not a stack trace to guess at.

`POLICY_DENIED` is the one that matters. It carries `retry: false` **and**
`alternative_route: false`, because an agent that answers a refusal by trying a
different tool is the precise failure this whole layer exists to prevent. Saying so
only in prose would leave it to the model's goodwill.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final

from revenue_sentinel.core.errors import RevenueSentinelError
from revenue_sentinel.core.types import JSONObject


@unique
class ToolErrorCode(StrEnum):
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    NOT_FOUND = "NOT_FOUND"
    POLICY_DENIED = "POLICY_DENIED"
    POLICY_ENGINE_UNAVAILABLE = "POLICY_ENGINE_UNAVAILABLE"
    """No policy engine is bound, so no decision about this write can exist.

    Deliberately **not** `POLICY_DENIED`. A denial is a decision about the request;
    this is a deployment fault, and collapsing the two would let a misconfigured server
    read as a policy outcome -- an operator would go looking for the rule that refused
    them, and there is no rule. Both fail closed and neither is retryable."""

    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    ADAPTER_ERROR = "ADAPTER_ERROR"


@dataclass(frozen=True, slots=True)
class ErrorPolicy:
    """What the agent should do about a given code."""

    retry: bool
    alternative_route: bool
    guidance: str


# BUDGET_EXCEEDED has NO PRODUCER until Session 7. It is defined, mapped, and its
# handling is tested by injection -- but nothing in Session 4 raises it for real.
ERROR_POLICY: Final[dict[ToolErrorCode, ErrorPolicy]] = {
    ToolErrorCode.INVALID_ARGUMENTS: ErrorPolicy(
        retry=True, alternative_route=False, guidance="Correct the arguments and retry once."
    ),
    ToolErrorCode.NOT_FOUND: ErrorPolicy(
        retry=False,
        alternative_route=False,
        guidance="Record this as negative evidence. Do not retry.",
    ),
    ToolErrorCode.POLICY_DENIED: ErrorPolicy(
        retry=False,
        alternative_route=False,
        guidance=(
            "The policy layer refused this action. Stop. Do not retry, and do not "
            "attempt to achieve the same effect through a different tool."
        ),
    ),
    ToolErrorCode.POLICY_ENGINE_UNAVAILABLE: ErrorPolicy(
        retry=False,
        alternative_route=False,
        guidance=(
            "The server is misconfigured: a write tool was reached with no policy "
            "engine bound. This is not a decision about your request. Stop, and do "
            "not attempt the same effect through a different tool."
        ),
    ),
    ToolErrorCode.APPROVAL_REQUIRED: ErrorPolicy(
        retry=False,
        alternative_route=False,
        guidance="A human approval request is required. Halt and await the decision.",
    ),
    ToolErrorCode.RATE_LIMITED: ErrorPolicy(
        retry=True, alternative_route=False, guidance="Retry with backoff."
    ),
    ToolErrorCode.BUDGET_EXCEEDED: ErrorPolicy(
        retry=False, alternative_route=False, guidance="Halt the run."
    ),
    ToolErrorCode.ADAPTER_ERROR: ErrorPolicy(
        retry=True,
        alternative_route=False,
        guidance="Retry with backoff, then fail the node.",
    ),
}


class ToolFailureError(RevenueSentinelError):
    """A typed failure a handler or the gate raises; the dispatcher renders it."""

    def __init__(
        self, code: ToolErrorCode, message: str, *, detail: JSONObject | None = None
    ) -> None:
        self.code = code
        self.message = message
        self.detail = detail or {}
        super().__init__(f"{code.value}: {message}")

    @property
    def policy(self) -> ErrorPolicy:
        return ERROR_POLICY[self.code]
