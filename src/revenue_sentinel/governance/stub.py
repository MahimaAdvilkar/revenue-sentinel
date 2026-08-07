"""Stand-in policy engines. **Superseded in Session 5; kept for tests only.**

> `policy_engine.DeterministicPolicyEngine` is the real one. These two remain because
> a test that wants an unconditional yes or an unconditional no should say so directly
> rather than construct rule inputs that happen to produce one. Neither is bound
> anywhere in `src/` or `scripts/`, and a test asserts that.

Original description follows.

A stand-in policy engine for Session 4. **This is not the policy engine.**

It returns ALLOW for everything and exists only so the *mechanism* can be built and
tested a session before the rules are: a write tool cannot reach its adapter without a
decision, whoever makes it.

The real engine arrives in Session 5 with risk tiers, default-deny for unclassified
actions, escalation on ambiguity, and recorded `matched_rules` (ADR-0005).

Because this stub says yes to everything, **write tools are deliberately not wired
into the investigation graph in Session 4**. A stub that always allows, reachable from
the demo, would create an email draft with no approval -- precisely the behaviour this
system claims to prevent.
"""

from __future__ import annotations

from typing import Final

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.enums import PolicyDecision, RiskTier
from revenue_sentinel.governance.outcomes import PolicyOutcome

STUB_POLICY_VERSION: Final = "stub/session-4"


class StubPolicyEngine:
    """Allows everything, and says so in the reason it records."""

    version = STUB_POLICY_VERSION

    def authorize(self, *, tool_name: str, tier: RiskTier, arguments: JSONObject) -> PolicyOutcome:
        return PolicyOutcome(
            decision=PolicyDecision.ALLOW,
            risk_tier=tier,
            policy_version=STUB_POLICY_VERSION,
            matched_rules=("stub:allow-all",),
            reason=(
                f"Stub engine allowed {tool_name} without evaluating anything. "
                f"The real policy engine arrives in Session 5."
            ),
        )


class DenyAllPolicyEngine:
    """Refuses everything. Used by tests to prove a denial never reaches an adapter."""

    version = "stub/deny-all"

    def authorize(self, *, tool_name: str, tier: RiskTier, arguments: JSONObject) -> PolicyOutcome:
        return PolicyOutcome(
            decision=PolicyDecision.DENY,
            risk_tier=tier,
            policy_version=self.version,
            matched_rules=("stub:deny-all",),
            reason=f"{tool_name} was refused by the deny-all engine.",
        )
