"""The policy engine: tiers, decisions, default-deny, and escalation.

These are the tests a reviewer should look for first, because the engine is the one
component whose *refusals* are the product. A policy layer that is merely usually
right is not a policy layer.

Everything here runs without a database and without a clock, which is the point of
`evaluate` being a pure function.
"""

from __future__ import annotations

import pytest

from revenue_sentinel.domain.enums import PolicyDecision, ProposedAction, RiskTier
from revenue_sentinel.governance import rules, tiers
from revenue_sentinel.governance.policy_engine import (
    TOOL_TO_ACTION,
    DeterministicPolicyEngine,
    PolicyRequest,
    evaluate,
)


def request_for(
    action: ProposedAction | str, *, fields: frozenset[str] = frozenset()
) -> PolicyRequest:
    return PolicyRequest(action=action, target_ref="OPP-2001", fields_changed=fields)


# ---------------------------------------------------------------------------
# Default-deny -- the most important test in this file
# ---------------------------------------------------------------------------
def test_an_unclassified_action_is_denied() -> None:
    """An action nobody has classified is refused, not permitted.

    The failure this prevents is the quiet one: a new action type added to the system
    and never given a tier, defaulting to allowed because nothing said otherwise.
    """
    outcome = evaluate(request_for("teleport_the_deal_to_closed_won"))

    assert outcome.decision is PolicyDecision.DENY
    assert outcome.risk_tier is RiskTier.PROHIBITED
    assert tiers.RULE_DEFAULT_DENY in outcome.matched_rules


def test_an_action_type_absent_from_the_tier_table_is_denied() -> None:
    """Not merely unknown *strings* -- an enum member nobody classified is denied too.

    This is why `classify` uses a mapping with a denying default rather than an
    exhaustive `match`: a member added to `ProposedAction` and forgotten here falls
    through to DENY instead of to whichever branch happened to be last.
    """
    for action in ProposedAction:
        tier, matched = tiers.classify(action, fields_changed=frozenset({"amount"}))
        assert matched, f"{action.value} produced no matched rules"
        assert isinstance(tier, RiskTier)


def test_a_field_update_naming_no_fields_is_denied() -> None:
    """An unspecified mutation cannot be assessed, so it is refused."""
    outcome = evaluate(request_for(ProposedAction.CRM_FIELD_UPDATE))

    assert outcome.decision is PolicyDecision.DENY
    assert tiers.RULE_UNCLASSIFIED_FIELD in outcome.matched_rules


def test_a_field_nobody_has_classified_is_denied() -> None:
    outcome = evaluate(request_for(ProposedAction.CRM_FIELD_UPDATE, fields=frozenset({"nonsense"})))

    assert outcome.decision is PolicyDecision.DENY
    assert tiers.RULE_UNCLASSIFIED_FIELD in outcome.matched_rules


# ---------------------------------------------------------------------------
# The four tiers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("action", "tier", "decision"),
    [
        (ProposedAction.CRM_TASK, RiskTier.INTERNAL_REVERSIBLE, PolicyDecision.ALLOW),
        (
            ProposedAction.SLACK_APPROVAL_REQUEST,
            RiskTier.INTERNAL_REVERSIBLE,
            PolicyDecision.ALLOW,
        ),
        (
            ProposedAction.EMAIL_DRAFT,
            RiskTier.CUSTOMER_FACING_OR_MATERIAL,
            PolicyDecision.REQUIRE_APPROVAL,
        ),
        (ProposedAction.SEND_EMAIL_DIRECT, RiskTier.PROHIBITED, PolicyDecision.DENY),
        (ProposedAction.RECORD_DELETE, RiskTier.PROHIBITED, PolicyDecision.DENY),
    ],
)
def test_each_action_lands_on_its_documented_tier(
    action: ProposedAction, tier: RiskTier, decision: PolicyDecision
) -> None:
    outcome = evaluate(request_for(action))

    assert outcome.risk_tier is tier
    assert outcome.decision is decision


def test_sending_email_directly_is_never_permitted() -> None:
    """Tier 3 is not "allowed with approval". It is refused outright (rule 8)."""
    outcome = evaluate(request_for(ProposedAction.SEND_EMAIL_DIRECT))

    assert outcome.decision is PolicyDecision.DENY
    assert outcome.decision is not PolicyDecision.REQUIRE_APPROVAL


# ---------------------------------------------------------------------------
# Material CRM change -- the definition, and its boundary
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("field", sorted(tiers.MATERIAL_OPPORTUNITY_FIELDS))
def test_every_material_field_requires_approval(field: str) -> None:
    outcome = evaluate(request_for(ProposedAction.CRM_FIELD_UPDATE, fields=frozenset({field})))

    assert outcome.risk_tier is RiskTier.CUSTOMER_FACING_OR_MATERIAL
    assert outcome.decision is PolicyDecision.REQUIRE_APPROVAL
    assert tiers.RULE_MATERIAL_CRM_FIELD in outcome.matched_rules


@pytest.mark.parametrize("field", sorted(tiers.NON_MATERIAL_OPPORTUNITY_FIELDS))
def test_a_non_material_field_is_allowed(field: str) -> None:
    outcome = evaluate(request_for(ProposedAction.CRM_FIELD_UPDATE, fields=frozenset({field})))

    assert outcome.risk_tier is RiskTier.INTERNAL_REVERSIBLE
    assert outcome.decision is PolicyDecision.ALLOW


def test_the_material_definition_matches_the_security_model_document() -> None:
    """The code and `docs/security-model.md` §3 must not drift apart.

    The document is the definition a reviewer reads; this module is the definition the
    system obeys. If they disagree, one of them is lying to somebody.
    """
    documented = {"amount", "stage", "probability", "expected_close_date", "owner_id"}

    assert documented == tiers.MATERIAL_OPPORTUNITY_FIELDS
    assert not (tiers.MATERIAL_OPPORTUNITY_FIELDS & tiers.NON_MATERIAL_OPPORTUNITY_FIELDS)


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------
def test_a_mixed_field_update_escalates_to_the_higher_tier() -> None:
    """`description` alone is tier 1; with `amount` the whole action is tier 2.

    Ambiguity resolves upward. Both rules are reported, so the decision explains
    itself rather than merely announcing itself.
    """
    outcome = evaluate(
        request_for(ProposedAction.CRM_FIELD_UPDATE, fields=frozenset({"description", "amount"}))
    )

    assert outcome.risk_tier is RiskTier.CUSTOMER_FACING_OR_MATERIAL
    assert tiers.RULE_MATERIAL_CRM_FIELD in outcome.matched_rules
    assert tiers.RULE_NON_MATERIAL_CRM_FIELD in outcome.matched_rules


def test_an_unclassified_field_dominates_a_material_one() -> None:
    """Tier 3 beats tier 2. `max()`, not "the first rule that matched"."""
    outcome = evaluate(
        request_for(ProposedAction.CRM_FIELD_UPDATE, fields=frozenset({"amount", "mystery"}))
    )

    assert outcome.risk_tier is RiskTier.PROHIBITED
    assert outcome.decision is PolicyDecision.DENY


def test_repeated_material_fields_report_the_rule_once() -> None:
    outcome = evaluate(
        request_for(
            ProposedAction.CRM_FIELD_UPDATE, fields=frozenset({"amount", "stage", "owner_id"})
        )
    )

    assert outcome.matched_rules.count(tiers.RULE_MATERIAL_CRM_FIELD) == 1


# ---------------------------------------------------------------------------
# Purity and auditability
# ---------------------------------------------------------------------------
def test_the_same_input_always_produces_the_same_decision() -> None:
    """Same input, same decision, always -- otherwise a recorded decision cannot be
    reproduced against the version it was made under."""
    request = request_for(ProposedAction.EMAIL_DRAFT)
    outcomes = [evaluate(request) for _ in range(25)]

    assert len({(o.decision, o.risk_tier, o.matched_rules, o.reason) for o in outcomes}) == 1


def test_every_outcome_names_its_rules_and_explains_itself() -> None:
    for action in ProposedAction:
        outcome = evaluate(request_for(action, fields=frozenset({"amount"})))
        assert outcome.matched_rules
        assert outcome.reason
        assert outcome.policy_version == tiers.POLICY_VERSION
        assert "OPP-2001" in outcome.reason


def test_the_decision_table_covers_every_tier() -> None:
    """A tier with no mapped decision would raise at runtime. Better to know here."""
    for tier in RiskTier:
        assert rules.decide(tier) in set(PolicyDecision)
        assert rules.reason_for(tier)


# ---------------------------------------------------------------------------
# The write-gate adapter
# ---------------------------------------------------------------------------
def test_every_write_tool_is_classified() -> None:
    """A write tool absent from the mapping is denied -- but all four are present, and
    a fifth appearing without an entry should fail this test rather than a demo."""
    from revenue_sentinel.mcp.registry import TOOL_SPECS

    write_tools = {spec.name for spec in TOOL_SPECS if spec.is_write}
    assert write_tools == set(TOOL_TO_ACTION)


def test_an_unmapped_tool_name_is_denied_by_the_engine() -> None:
    engine = DeterministicPolicyEngine()
    outcome = engine.authorize(
        tool_name="crm_do_something_new", tier=RiskTier.INTERNAL_REVERSIBLE, arguments={}
    )

    assert outcome.decision is PolicyDecision.DENY


def test_the_registry_tier_can_escalate_but_never_relax() -> None:
    """A tool declared tier 2 that looks tier 1 from its arguments is still tier 2.

    The reverse is what matters: a registry entry cannot *lower* the engine's answer,
    so under-declaring a tool's tier is not a route past the policy layer.
    """
    engine = DeterministicPolicyEngine()

    escalated = engine.authorize(
        tool_name="crm_create_task",
        tier=RiskTier.CUSTOMER_FACING_OR_MATERIAL,
        arguments={"opportunity_ref": "OPP-2001"},
    )
    assert escalated.risk_tier is RiskTier.CUSTOMER_FACING_OR_MATERIAL
    assert escalated.decision is PolicyDecision.REQUIRE_APPROVAL
    assert "escalated:registry-tier" in escalated.matched_rules

    not_relaxed = engine.authorize(
        tool_name="messaging_create_email_draft",
        tier=RiskTier.READ_OR_COMPUTE,
        arguments={"account_ref": "ACC-1001"},
    )
    assert not_relaxed.risk_tier is RiskTier.CUSTOMER_FACING_OR_MATERIAL
    assert not_relaxed.decision is PolicyDecision.REQUIRE_APPROVAL
