"""Risk-tier classification -- the part of policy that reads the action, not the rules.

`docs/security-model.md` §3 defines four tiers and, critically, defines **material CRM
change** explicitly rather than leaving it to judgement. That definition is transcribed
here as data, and a test asserts this module and that document still agree. A
definition that lives in prose and is re-interpreted in code is a definition that
drifts.

Two properties this module exists to guarantee:

* **Default-deny.** An action type this module does not recognise classifies as
  `PROHIBITED`, not as "probably fine". The `case _` at the bottom of `classify` is the
  single most important line in the file.
* **Escalation on ambiguity.** When several rules match, the tier is `max()` of them
  and every matched rule is reported. `RiskTier` is an `IntEnum` precisely so caution
  is arithmetic rather than a convention someone remembers to follow.
"""

from __future__ import annotations

from typing import Final

from revenue_sentinel.domain.enums import ProposedAction, RiskTier

POLICY_VERSION: Final = "policy/v1"
"""Stamped onto every outcome and every `policy_evaluations` row. Bump when a rule
changes, so a past decision can be read against the rules that actually produced it."""

MATERIAL_OPPORTUNITY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "amount",
        "stage",
        "probability",
        "expected_close_date",
        "owner_id",
    }
)
"""Transcribed verbatim from `docs/security-model.md` §3.

> *"any write to `amount`, `stage`, `probability`, `expected_close_date`, `owner_id`,
> or any delete. Writes to `description` or the addition of a task are not material."*

Deletes are handled separately below, because a delete is material regardless of which
field is named."""

NON_MATERIAL_OPPORTUNITY_FIELDS: Final[frozenset[str]] = frozenset({"description", "next_step"})
"""Explicitly *not* material. Listed rather than inferred from the complement of the set
above, so a field nobody has classified falls through to default-deny instead of being
silently treated as harmless."""


# ---------------------------------------------------------------------------
# Rule names -- stable identifiers recorded in `matched_rules`
# ---------------------------------------------------------------------------
RULE_READ_OR_COMPUTE: Final = "tier0:read-or-compute"
RULE_INTERNAL_REVERSIBLE: Final = "tier1:internal-reversible"
RULE_CUSTOMER_FACING: Final = "tier2:customer-facing"
RULE_MATERIAL_CRM_FIELD: Final = "tier2:material-crm-field"
RULE_NON_MATERIAL_CRM_FIELD: Final = "tier1:non-material-crm-field"
RULE_PROHIBITED_CAPABILITY: Final = "tier3:prohibited-capability"
RULE_UNCLASSIFIED_FIELD: Final = "tier3:unclassified-crm-field"
RULE_DEFAULT_DENY: Final = "tier3:default-deny"


_TIER_BY_ACTION: Final[dict[ProposedAction, tuple[RiskTier, tuple[str, ...]]]] = {
    ProposedAction.CRM_TASK: (RiskTier.INTERNAL_REVERSIBLE, (RULE_INTERNAL_REVERSIBLE,)),
    ProposedAction.SLACK_APPROVAL_REQUEST: (
        RiskTier.INTERNAL_REVERSIBLE,
        (RULE_INTERNAL_REVERSIBLE,),
    ),
    ProposedAction.EMAIL_DRAFT: (
        RiskTier.CUSTOMER_FACING_OR_MATERIAL,
        (RULE_CUSTOMER_FACING,),
    ),
    ProposedAction.SEND_EMAIL_DIRECT: (RiskTier.PROHIBITED, (RULE_PROHIBITED_CAPABILITY,)),
    ProposedAction.RECORD_DELETE: (RiskTier.PROHIBITED, (RULE_PROHIBITED_CAPABILITY,)),
}
"""`CRM_FIELD_UPDATE` is absent deliberately -- its tier depends on which fields, so it
is handled before this lookup. Every other member is classified here, and a member
missing from both paths is denied."""


def classify(
    action: ProposedAction | str, *, fields_changed: frozenset[str] = frozenset()
) -> tuple[RiskTier, tuple[str, ...]]:
    """The tier this action falls into, and the rules that put it there.

    `action` is typed as `ProposedAction | str` deliberately. A plain string that is
    not a member reaches the `case _` branch and is denied -- which is what should
    happen to an action type nobody has classified, including one invented by a model
    or added to an enum without being classified here.
    """
    try:
        resolved = ProposedAction(action)
    except ValueError:
        return RiskTier.PROHIBITED, (RULE_DEFAULT_DENY,)

    if resolved is ProposedAction.CRM_FIELD_UPDATE:
        return _classify_field_update(fields_changed)

    # A `.get` with a denying default rather than a `match` with a `case _`. The
    # exhaustive `match` mypy prefers would make the default branch unreachable *and*
    # dead -- so a member added to `ProposedAction` and forgotten here would fall
    # through to whatever the last branch happened to be. This way it is denied, which
    # is the behaviour default-deny is supposed to mean.
    classified = _TIER_BY_ACTION.get(resolved)
    if classified is None:
        return RiskTier.PROHIBITED, (RULE_DEFAULT_DENY,)
    return classified


def _classify_field_update(fields_changed: frozenset[str]) -> tuple[RiskTier, tuple[str, ...]]:
    """A CRM field update is tier 1 or tier 2 depending on *which* fields.

    A field named in neither set is unclassified and therefore tier 3. That is the
    conservative reading and the one the security model asks for: the system does not
    get to decide that an unfamiliar field is probably harmless.

    An update naming no fields at all is also tier 3 -- an unspecified mutation cannot
    be assessed, and "assume it is fine" is the wrong default for the one code path
    whose job is to be suspicious.
    """
    if not fields_changed:
        return RiskTier.PROHIBITED, (RULE_UNCLASSIFIED_FIELD,)

    matched: list[str] = []
    tier = RiskTier.READ_OR_COMPUTE

    for field in sorted(fields_changed):
        if field in MATERIAL_OPPORTUNITY_FIELDS:
            tier = max(tier, RiskTier.CUSTOMER_FACING_OR_MATERIAL)
            matched.append(RULE_MATERIAL_CRM_FIELD)
        elif field in NON_MATERIAL_OPPORTUNITY_FIELDS:
            tier = max(tier, RiskTier.INTERNAL_REVERSIBLE)
            matched.append(RULE_NON_MATERIAL_CRM_FIELD)
        else:
            tier = max(tier, RiskTier.PROHIBITED)
            matched.append(RULE_UNCLASSIFIED_FIELD)

    # Deduplicated but order-stable: three material fields produce one rule name, not
    # three copies of it.
    seen: dict[str, None] = dict.fromkeys(matched)
    return tier, tuple(seen)
