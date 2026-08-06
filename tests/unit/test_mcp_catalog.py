"""The tool catalog, its strictness, and the honesty of its adapters.

The two assertions that matter most:

* **Every published schema sets `additionalProperties: false`.** The MCP SDK's
  ergonomic decorator does not, and silently accepts unknown arguments -- so this is
  the check that keeps `docs/mcp-design.md` §4 from being a false claim.
* **No broad tool exists.** `run_sql`, `http_request`, and `messaging_send_email` are
  absent by design (rule 15). Tier 3 is not a tool that gets denied; it is a tool that
  was never built.
"""

from __future__ import annotations

import ast
from types import ModuleType

import pytest

from revenue_sentinel.core.config import PROJECT_ROOT
from revenue_sentinel.domain.enums import RiskTier
from revenue_sentinel.integrations.simulated import (
    crm,
    engagement,
    enrichment,
    messaging,
    product,
    support,
)
from revenue_sentinel.integrations.status import SIMULATED, status_of
from revenue_sentinel.mcp.errors import ERROR_POLICY, ToolErrorCode
from revenue_sentinel.mcp.registry import (
    EXPECTED_TOOL_COUNT,
    REGISTRY,
    TOOL_SPECS,
    WRITE_TOOL_COUNT,
)

ADAPTER_MODULES = (crm, product, engagement, support, enrichment, messaging)

EXPECTED_WRITE_TOOLS = {
    "crm_create_task",
    "crm_update_opportunity",
    "messaging_create_email_draft",
    "messaging_send_slack_approval",
}

FORBIDDEN_TOOL_NAMES = (
    "messaging_send_email",
    "send_email",
    "run_sql",
    "http_request",
    "execute",
    "query",
)

REQUIRED_DOC_SECTIONS = ("**API.**", "**Auth.**", "**Rate limits.**")


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------
def test_fifteen_tools_are_registered() -> None:
    assert len(REGISTRY) == EXPECTED_TOOL_COUNT == 15


def test_registry_and_specs_agree() -> None:
    assert len(TOOL_SPECS) == len(REGISTRY)
    assert {spec.name for spec in TOOL_SPECS} == set(REGISTRY)


def test_exactly_four_tools_are_writes() -> None:
    writes = {spec.name for spec in TOOL_SPECS if spec.is_write}
    assert writes == EXPECTED_WRITE_TOOLS
    assert len(writes) == WRITE_TOOL_COUNT


@pytest.mark.parametrize("forbidden", FORBIDDEN_TOOL_NAMES)
def test_no_broad_or_prohibited_tool_exists(forbidden: str) -> None:
    """A broad tool is a broad blast radius. Sending email is Tier 3 -- absent."""
    assert forbidden not in REGISTRY
    assert not any(forbidden in name for name in REGISTRY)


def test_every_read_tool_is_tier_zero() -> None:
    for spec in TOOL_SPECS:
        if not spec.is_write:
            assert spec.tier is RiskTier.READ_OR_COMPUTE, spec.name


@pytest.mark.parametrize(
    ("tool_name", "expected_tier"),
    [
        ("crm_create_task", RiskTier.INTERNAL_REVERSIBLE),
        ("messaging_send_slack_approval", RiskTier.INTERNAL_REVERSIBLE),
        ("crm_update_opportunity", RiskTier.CUSTOMER_FACING_OR_MATERIAL),
        ("messaging_create_email_draft", RiskTier.CUSTOMER_FACING_OR_MATERIAL),
    ],
)
def test_write_tool_tiers_match_the_security_model(tool_name: str, expected_tier: RiskTier) -> None:
    assert REGISTRY[tool_name].tier is expected_tier


def test_no_write_tool_is_tier_three() -> None:
    """Tier 3 is not permitted at all, so nothing may be registered at it."""
    assert all(spec.tier is not RiskTier.PROHIBITED for spec in TOOL_SPECS)


def test_every_tool_has_a_description() -> None:
    for spec in TOOL_SPECS:
        assert len(spec.description) > 20, spec.name


# ---------------------------------------------------------------------------
# Strictness
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("spec", TOOL_SPECS, ids=lambda s: s.name)
def test_every_published_schema_forbids_unknown_arguments(spec: object) -> None:
    """The check the SDK's own decorator would fail."""
    schema = spec.input_schema  # type: ignore[attr-defined]
    assert schema["additionalProperties"] is False
    assert schema["type"] == "object"


@pytest.mark.parametrize("spec", TOOL_SPECS, ids=lambda s: s.name)
def test_every_schema_declares_its_required_arguments(spec: object) -> None:
    schema = spec.input_schema  # type: ignore[attr-defined]
    assert "properties" in schema
    if schema["properties"]:
        assert "required" in schema


@pytest.mark.parametrize("spec", TOOL_SPECS, ids=lambda s: s.name)
def test_every_args_model_rejects_an_unknown_field(spec: object) -> None:
    """Enforcement, not just advertisement."""
    from pydantic import ValidationError

    model = spec.args_model  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        model.model_validate({"definitely_not_a_field": 1})


# ---------------------------------------------------------------------------
# Adapter honesty (ADR-0004)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("module", ADAPTER_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_every_adapter_declares_simulated(module: ModuleType) -> None:
    assert status_of(module) == SIMULATED


@pytest.mark.parametrize("module", ADAPTER_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_every_adapter_documents_its_real_counterpart(module: ModuleType) -> None:
    """The section that turns simulation from an excuse into a design artifact."""
    doc = module.__doc__ or ""
    assert "What changes when this becomes real" in doc
    for section in REQUIRED_DOC_SECTIONS:
        assert section in doc, f"{module.__name__} omits {section}"
    assert len(doc) > 900, f"{module.__name__} documents its real counterpart too thinly"


def test_a_module_without_a_status_declaration_is_fatal() -> None:
    """Defaulting would be safe today and wrong the first time it mattered."""
    from revenue_sentinel.integrations.status import MissingIntegrationStatusError

    blank = ModuleType("blank_adapter")
    with pytest.raises(MissingIntegrationStatusError):
        status_of(blank)


def test_no_adapter_exposes_a_send_capability() -> None:
    """Checked against the source, not the docs: `send` must not appear as a method
    on the messaging adapter beyond the internal Slack notification."""
    path = PROJECT_ROOT / "src" / "revenue_sentinel" / "integrations" / "simulated" / "messaging.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    methods = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    assert "send_email" not in methods
    assert methods <= {"create_email_draft", "send_slack_approval", "__init__"}


# ---------------------------------------------------------------------------
# Error policy
# ---------------------------------------------------------------------------
def test_all_seven_error_codes_have_a_policy() -> None:
    assert set(ERROR_POLICY) == set(ToolErrorCode)
    assert len(ToolErrorCode) == 7


def test_policy_denied_forbids_retry_and_rerouting() -> None:
    """An agent that answers a denial by trying another tool is the failure this
    layer exists to prevent, so the refusal is machine-readable."""
    policy = ERROR_POLICY[ToolErrorCode.POLICY_DENIED]

    assert policy.retry is False
    assert policy.alternative_route is False
    assert "different tool" in policy.guidance


def test_no_error_code_ever_suggests_an_alternative_route() -> None:
    assert all(not policy.alternative_route for policy in ERROR_POLICY.values())


@pytest.mark.parametrize(
    ("code", "retry"),
    [
        (ToolErrorCode.INVALID_ARGUMENTS, True),
        (ToolErrorCode.NOT_FOUND, False),
        (ToolErrorCode.POLICY_DENIED, False),
        (ToolErrorCode.APPROVAL_REQUIRED, False),
        (ToolErrorCode.RATE_LIMITED, True),
        (ToolErrorCode.BUDGET_EXCEEDED, False),
        (ToolErrorCode.ADAPTER_ERROR, True),
    ],
)
def test_retry_guidance_per_code(code: ToolErrorCode, retry: bool) -> None:
    assert ERROR_POLICY[code].retry is retry


def test_budget_exceeded_is_defined_but_has_no_producer_yet() -> None:
    """Session 7 owns the Cost Governor. Nothing raises this today, and the project
    documentation says so rather than implying the ceiling is enforced."""
    from revenue_sentinel.mcp import dispatcher

    source = (PROJECT_ROOT / "src" / "revenue_sentinel" / "mcp" / "dispatcher.py").read_text(
        encoding="utf-8"
    )

    # Reachable only by injection, never raised by the dispatcher's own logic.
    assert "BUDGET_EXCEEDED" in source
    assert ToolErrorCode.BUDGET_EXCEEDED in dispatcher._INJECTED_TO_CODE.values()
