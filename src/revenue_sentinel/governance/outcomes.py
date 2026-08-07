"""What a policy decision *is*, independent of who made it.

Session 4 defined `PolicyOutcome` inside `stub.py`, which was fine while the stub was
the only engine. It is not fine now: the real engine importing its result type from a
module whose docstring begins "this is not the policy engine" would be exactly the kind
of thing a reader trips over. The type moves here; both engines and the gate import it
from one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from revenue_sentinel.domain.enums import PolicyDecision, RiskTier


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    """A decision about one action.

    `matched_rules` is not decoration. A decision a human cannot audit is a decision
    they have to take on trust, and the whole point of a deterministic engine is that
    they do not have to -- so every outcome names the rules that produced it, and
    `reason` states it in a sentence a revenue leader can read.
    """

    decision: PolicyDecision
    risk_tier: RiskTier
    policy_version: str
    matched_rules: tuple[str, ...]
    reason: str
