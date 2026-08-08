"""Telling the write gate that an approval already exists.

Found by a test, and worth explaining because the bug was invisible from either side.

`authorize_execution` verifies the `ApprovalRequest` and grants. The MCP write gate then
**independently re-evaluates policy** -- which is correct and deliberate, since the gate
must never trust its caller -- and the deterministic engine, knowing nothing about
approvals, answers `REQUIRE_APPROVAL` again. The result was a Tier 2 action that could be
approved by a human and still never run: the gate refused it forever.

The fix is not to weaken the gate. It is to hand the gate the *evidence* the caller
already verified, scoped as narrowly as it can be:

* it converts `REQUIRE_APPROVAL` to `ALLOW` **only** for the exact tool the grant names,
* **never** converts `DENY` -- an approval cannot override a denial, here as everywhere,
* records the approving request's id in `matched_rules`, so the ledger says *why* the
  write was permitted rather than merely that it was,
* and is constructed per action, from a grant, so there is no long-lived object that
  could accidentally permit a second one.

A blanket "execution bypasses approval checks" flag would have been three lines shorter
and would have deleted the guarantee.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.enums import PolicyDecision, RiskTier
from revenue_sentinel.governance.outcomes import PolicyOutcome
from revenue_sentinel.governance.policy_engine import DeterministicPolicyEngine
from revenue_sentinel.governance.tiers import POLICY_VERSION

APPROVED_RULE: Final = "approved:human-decision-recorded"


class ApprovedActionPolicyEngine:
    """The deterministic engine, plus proof that one specific action was approved."""

    version = POLICY_VERSION

    def __init__(self, *, tool_name: str, approval_request_id: UUID) -> None:
        self._tool_name = tool_name
        self._approval_request_id = approval_request_id
        self._inner = DeterministicPolicyEngine()

    def authorize(self, *, tool_name: str, tier: RiskTier, arguments: JSONObject) -> PolicyOutcome:
        outcome = self._inner.authorize(tool_name=tool_name, tier=tier, arguments=arguments)

        # A denial stays a denial. This is the branch that must never grow an exception.
        if outcome.decision is not PolicyDecision.REQUIRE_APPROVAL:
            return outcome

        if tool_name != self._tool_name:
            # The grant covers one tool. Anything else is unapproved, whatever this
            # object happens to be holding.
            return outcome

        return PolicyOutcome(
            decision=PolicyDecision.ALLOW,
            risk_tier=outcome.risk_tier,
            policy_version=outcome.policy_version,
            matched_rules=(*outcome.matched_rules, APPROVED_RULE),
            reason=(
                f"{outcome.reason} Permitted because approval request "
                f"{self._approval_request_id} was recorded as approved by a person."
            ),
        )
