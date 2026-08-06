"""The write gate.

`docs/mcp-design.md` §2: *"a write tool cannot reach its adapter without a policy
decision. This is enforced in the server, not left to the caller's discipline."*

Two properties, both tested:

* **No engine bound → a write raises.** Not "allows by default", not "warns". A
  system that can be configured into performing unauthorised writes is a system that
  eventually will be.
* **A non-ALLOW decision returns before the adapter is reached.** Tests use a spy
  adapter that records whether it was called at all.

Reads bypass the gate entirely -- Tier 0 has nothing to authorise, and routing reads
through a policy check would make the check look load-bearing where it is not.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.enums import PolicyDecision, RiskTier
from revenue_sentinel.governance.stub import PolicyOutcome
from revenue_sentinel.mcp.errors import ToolErrorCode, ToolFailureError


@runtime_checkable
class PolicyEngine(Protocol):
    """Whatever decides whether a write may happen."""

    @property
    def version(self) -> str: ...

    def authorize(
        self, *, tool_name: str, tier: RiskTier, arguments: JSONObject
    ) -> PolicyOutcome: ...


class MissingPolicyEngineError(RuntimeError):
    """A write tool was invoked with no policy engine bound."""


def authorize_write(
    *, tool_name: str, tier: RiskTier, arguments: JSONObject, engine: PolicyEngine | None
) -> PolicyOutcome:
    """Return the decision, or raise/fail. Never returns without one."""
    if engine is None:
        raise MissingPolicyEngineError(
            f"{tool_name} is a write tool and no policy engine is bound. "
            f"Write tools cannot execute without a decision."
        )

    outcome = engine.authorize(tool_name=tool_name, tier=tier, arguments=arguments)

    if outcome.decision is PolicyDecision.REQUIRE_APPROVAL:
        raise ToolFailureError(
            ToolErrorCode.APPROVAL_REQUIRED,
            f"{tool_name} requires human approval before it can run.",
            detail={"policy_version": outcome.policy_version, "reason": outcome.reason},
        )
    if outcome.decision is not PolicyDecision.ALLOW:
        raise ToolFailureError(
            ToolErrorCode.POLICY_DENIED,
            f"{tool_name} was refused by the policy layer.",
            detail={
                "policy_version": outcome.policy_version,
                "matched_rules": list(outcome.matched_rules),
                "reason": outcome.reason,
            },
        )
    return outcome
