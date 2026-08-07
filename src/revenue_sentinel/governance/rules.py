"""Tier -> decision. The second half of policy, and deliberately the boring half.

`tiers.py` answers "how dangerous is this?". This module answers "so what?", and the
mapping is a table rather than a function body because the whole value of a
deterministic policy engine is that a human can read the rules without reading the
code.

The mapping is exactly `docs/security-model.md` §3, and a test asserts they agree.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from revenue_sentinel.domain.enums import PolicyDecision, RiskTier

DECISION_BY_TIER: Final[MappingProxyType[RiskTier, PolicyDecision]] = MappingProxyType(
    {
        RiskTier.READ_OR_COMPUTE: PolicyDecision.ALLOW,
        RiskTier.INTERNAL_REVERSIBLE: PolicyDecision.ALLOW,
        RiskTier.CUSTOMER_FACING_OR_MATERIAL: PolicyDecision.REQUIRE_APPROVAL,
        RiskTier.PROHIBITED: PolicyDecision.DENY,
    }
)
"""Read-only. A mutable module-level dict is a policy engine one `import` away from
being reconfigured at runtime, which would make `policy_version` a lie."""

TIER_REASON: Final[MappingProxyType[RiskTier, str]] = MappingProxyType(
    {
        RiskTier.READ_OR_COMPUTE: (
            "Reads and computations mutate nothing outside the system and are permitted."
        ),
        RiskTier.INTERNAL_REVERSIBLE: (
            "Internal and reversible: no customer is contacted and the change is easily "
            "undone, so it is permitted and audited."
        ),
        RiskTier.CUSTOMER_FACING_OR_MATERIAL: (
            "This reaches a customer or materially changes CRM data, so a person must "
            "approve it before it can run."
        ),
        RiskTier.PROHIBITED: (
            "This is not a capability the system has. It is refused outright, and no "
            "alternative route to the same effect is permitted."
        ),
    }
)


def decide(tier: RiskTier) -> PolicyDecision:
    """The decision for a tier.

    `KeyError` rather than a default: an unmapped tier is a programming error, and
    inventing an answer for it would be the one failure mode this module exists to
    prevent.
    """
    return DECISION_BY_TIER[tier]


def reason_for(tier: RiskTier) -> str:
    return TIER_REASON[tier]
