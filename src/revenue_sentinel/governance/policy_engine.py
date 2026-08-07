"""The policy engine. A pure function, and an adapter that lets the write gate call it.

**`evaluate` performs no I/O, reads no clock, and holds no state.** Same input, same
decision, always -- which is what makes a recorded decision reproducible a year later
against the `policy_version` it was made under, and what lets the whole tier table be
tested without a database.

The engine does not *do* anything. It returns an outcome; `mcp/gate.py` is what turns a
non-ALLOW outcome into a refused tool call, and in Session 5 nothing executes at all.
Keeping "decide" and "act" in different modules is what makes it possible to state that
sentence and mean it.

Two guarantees this module inherits from `tiers.py` rather than restating:

* an action nobody has classified is **denied**, not permitted;
* when several rules match, the tier is the **highest** of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.enums import PolicyDecision, ProposedAction, RiskTier
from revenue_sentinel.governance import rules, tiers
from revenue_sentinel.governance.outcomes import PolicyOutcome

TOOL_TO_ACTION: dict[str, ProposedAction] = {
    "crm_create_task": ProposedAction.CRM_TASK,
    "crm_update_opportunity": ProposedAction.CRM_FIELD_UPDATE,
    "messaging_create_email_draft": ProposedAction.EMAIL_DRAFT,
    "messaging_send_slack_approval": ProposedAction.SLACK_APPROVAL_REQUEST,
}
"""The four write tools, mapped to what they actually do.

A tool absent from this mapping is not classified, so `authorize` denies it. That is
the property that matters when a fifth write tool is added by someone who forgets this
file exists."""


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    """Everything the engine is allowed to consider.

    Deliberately small. There is no session, no user object, and no free text from a
    model -- an engine that could read the intervention's rationale would be an engine
    an injected instruction could argue with (rule 14).
    """

    action: ProposedAction | str
    target_ref: str
    fields_changed: frozenset[str] = field(default_factory=frozenset)
    actor: str = "agent:strategy"


def evaluate(request: PolicyRequest) -> PolicyOutcome:
    """Classify, decide, and explain. The whole engine."""
    tier, matched = tiers.classify(request.action, fields_changed=request.fields_changed)
    decision = rules.decide(tier)

    return PolicyOutcome(
        decision=decision,
        risk_tier=tier,
        policy_version=tiers.POLICY_VERSION,
        matched_rules=matched,
        reason=_reason(request, tier, decision),
    )


def _reason(request: PolicyRequest, tier: RiskTier, decision: PolicyDecision) -> str:
    """A sentence a revenue leader can read, naming the action and the target."""
    action = request.action.value if isinstance(request.action, ProposedAction) else request.action
    detail = rules.reason_for(tier)

    if request.fields_changed:
        fields = ", ".join(sorted(request.fields_changed))
        return f"{action} on {request.target_ref} (fields: {fields}) -> {decision.value}. {detail}"
    return f"{action} on {request.target_ref} -> {decision.value}. {detail}"


class DeterministicPolicyEngine:
    """Adapts `evaluate` to the `PolicyEngine` Protocol the write gate expects.

    The gate's Protocol is `authorize(tool_name, tier, arguments)`. That signature is
    from Session 4 and is not changed here -- the gate keeps working, including its
    test that a write with **no** engine bound still raises. Session 5 supplies an
    engine to bind; it does not loosen what happens when none is.

    The `tier` the gate passes is the tool's *static* tier from the registry. It is
    combined with the tier computed from the arguments by `max()`, so a tool declared
    tier 1 that is asked to change `amount` is still tier 2. The registry cannot
    under-declare its way past the policy layer.
    """

    version = tiers.POLICY_VERSION

    def authorize(self, *, tool_name: str, tier: RiskTier, arguments: JSONObject) -> PolicyOutcome:
        action = TOOL_TO_ACTION.get(tool_name, tool_name)
        outcome = evaluate(
            PolicyRequest(
                action=action,
                target_ref=_target_of(arguments),
                fields_changed=_fields_of(arguments),
                actor="agent:mcp",
            )
        )

        effective = max(outcome.risk_tier, tier)
        if effective is outcome.risk_tier:
            return outcome

        # The registry declared a higher tier than the arguments imply. Escalate, and
        # say so -- silently taking the stricter answer would hide a registry/engine
        # disagreement that someone should look at.
        return PolicyOutcome(
            decision=rules.decide(effective),
            risk_tier=effective,
            policy_version=outcome.policy_version,
            matched_rules=(*outcome.matched_rules, "escalated:registry-tier"),
            reason=(
                f"{outcome.reason} Escalated to tier {int(effective)} because the tool "
                f"registry declares {tool_name} at that tier."
            ),
        )


def _target_of(arguments: JSONObject) -> str:
    for key in ("opportunity_ref", "account_ref", "channel_ref", "incident_ref"):
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    return "unknown"


def _fields_of(arguments: JSONObject) -> frozenset[str]:
    """`crm_update_opportunity` names the field it changes; other tools change none."""
    field_name = arguments.get("field")
    return frozenset({field_name}) if isinstance(field_name, str) else frozenset()
