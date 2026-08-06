"""The tool catalog -- 15 tools, each with its tier, its strictness, and its adapter.

The registry is the single source of truth for what exists. `docs/mcp-design.md` §3 is
the prose version; this is the one the server publishes and the dispatcher enforces, so
they cannot drift without a test noticing.

**There is no `messaging_send_email`, no `run_sql`, and no `http_request`.** That is
the design, not an omission (rule 15).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.enums import RiskTier
from revenue_sentinel.mcp import schemas
from revenue_sentinel.mcp.context import ToolContext
from revenue_sentinel.mcp.tools import compute, read, write


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Everything the server and dispatcher need to know about one tool."""

    name: str
    description: str
    tier: RiskTier
    is_write: bool
    adapter_key: str
    args_model: type[schemas.ToolArgs]
    handler: Callable[[schemas.ToolArgs, ToolContext], JSONObject]

    @property
    def input_schema(self) -> JSONObject:
        """Published JSON Schema, with `additionalProperties: false` verified."""
        return schemas.strict_schema(self.args_model)


def _spec(
    name: str,
    description: str,
    tier: RiskTier,
    adapter_key: str,
    args_model: type[schemas.ToolArgs],
    handler: object,
    *,
    is_write: bool = False,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        tier=tier,
        is_write=is_write,
        adapter_key=adapter_key,
        args_model=args_model,
        handler=handler,  # type: ignore[arg-type]
    )


TOOL_SPECS: Final[tuple[ToolSpec, ...]] = (
    # -- Read, Tier 0 --------------------------------------------------------
    _spec(
        "crm_search_accounts",
        "Search accounts by name fragment, optionally filtered by segment.",
        RiskTier.READ_OR_COMPUTE,
        "crm",
        schemas.SearchAccountsArgs,
        read.crm_search_accounts,
    ),
    _spec(
        "crm_get_account",
        "Fetch one account by business reference.",
        RiskTier.READ_OR_COMPUTE,
        "crm",
        schemas.AccountRefArgs,
        read.crm_get_account,
    ),
    _spec(
        "crm_get_opportunity",
        "Fetch one opportunity by business reference.",
        RiskTier.READ_OR_COMPUTE,
        "crm",
        schemas.OpportunityRefArgs,
        read.crm_get_opportunity,
    ),
    _spec(
        "crm_list_account_activities",
        "List logged sales activity for an account since a given instant.",
        RiskTier.READ_OR_COMPUTE,
        "crm",
        schemas.ListActivitiesArgs,
        read.crm_list_account_activities,
    ),
    _spec(
        "product_get_usage_summary",
        "Weekly product-usage rollups for an account across a period.",
        RiskTier.READ_OR_COMPUTE,
        "product",
        schemas.UsageSummaryArgs,
        read.product_get_usage_summary,
    ),
    _spec(
        "engagement_get_email_activity",
        "Email sends, opens and clicks for an account since a given instant.",
        RiskTier.READ_OR_COMPUTE,
        "engagement",
        schemas.EngagementArgs,
        read.engagement_get_email_activity,
    ),
    _spec(
        "engagement_get_meeting_activity",
        "Meetings held with an account since a given instant.",
        RiskTier.READ_OR_COMPUTE,
        "engagement",
        schemas.EngagementArgs,
        read.engagement_get_meeting_activity,
    ),
    _spec(
        "support_get_open_issues",
        "Open and pending support issues for an account.",
        RiskTier.READ_OR_COMPUTE,
        "support",
        schemas.AccountRefArgs,
        read.support_get_open_issues,
    ),
    _spec(
        "enrichment_get_company_profile",
        "Firmographic profile for an account.",
        RiskTier.READ_OR_COMPUTE,
        "enrichment",
        schemas.AccountRefArgs,
        read.enrichment_get_company_profile,
    ),
    # -- Write, policy-gated -------------------------------------------------
    _spec(
        "crm_create_task",
        "Create an internal follow-up task on an opportunity.",
        RiskTier.INTERNAL_REVERSIBLE,
        "crm",
        schemas.CreateTaskArgs,
        write.crm_create_task,
        is_write=True,
    ),
    _spec(
        "crm_update_opportunity",
        "Update one field on an opportunity. Material CRM change.",
        RiskTier.CUSTOMER_FACING_OR_MATERIAL,
        "crm",
        schemas.UpdateOpportunityArgs,
        write.crm_update_opportunity,
        is_write=True,
    ),
    _spec(
        "messaging_create_email_draft",
        "Create an unsent email draft. Sending is not a capability of this system.",
        RiskTier.CUSTOMER_FACING_OR_MATERIAL,
        "messaging",
        schemas.CreateEmailDraftArgs,
        write.messaging_create_email_draft,
        is_write=True,
    ),
    _spec(
        "messaging_send_slack_approval",
        "Post an internal Slack notification requesting a human decision.",
        RiskTier.INTERNAL_REVERSIBLE,
        "messaging",
        schemas.SlackApprovalArgs,
        write.messaging_send_slack_approval,
        is_write=True,
    ),
    # -- Computation and audit, Tier 0 ---------------------------------------
    _spec(
        "analytics_calculate_pipeline_impact",
        "Compute weighted and at-risk pipeline value deterministically. "
        "The caller supplies inputs and receives the figure; it cannot supply one.",
        RiskTier.READ_OR_COMPUTE,
        "crm",
        schemas.PipelineImpactArgs,
        compute.analytics_calculate_pipeline_impact,
    ),
    _spec(
        "audit_write_event",
        "Append an event to the incident audit trail.",
        RiskTier.READ_OR_COMPUTE,
        "crm",
        schemas.AuditEventArgs,
        compute.audit_write_event,
    ),
)

REGISTRY: Final[dict[str, ToolSpec]] = {spec.name: spec for spec in TOOL_SPECS}

EXPECTED_TOOL_COUNT: Final = 15
WRITE_TOOL_COUNT: Final = 4


def get_spec(tool_name: str) -> ToolSpec | None:
    return REGISTRY.get(tool_name)
