"""The nine read tools -- Tier 0, always permitted.

Handlers are thin by design: unpack validated arguments, call one adapter method,
return the payload. Everything else -- validation, the gate, the envelope, the ledger --
happens in the dispatcher, so a handler cannot forget any of it.
"""

from __future__ import annotations

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.mcp.context import ToolContext
from revenue_sentinel.mcp.errors import ToolErrorCode, ToolFailureError
from revenue_sentinel.mcp.schemas import (
    AccountRefArgs,
    EngagementArgs,
    ListActivitiesArgs,
    OpportunityRefArgs,
    SearchAccountsArgs,
    UsageSummaryArgs,
)


def _require(payload: JSONObject, what: str, ref: str) -> JSONObject:
    """An empty adapter payload means the entity does not exist.

    `NOT_FOUND` rather than an empty success: an agent must be able to record a
    negative result as evidence, and an empty object looks like a present-but-blank
    record.
    """
    if not payload:
        raise ToolFailureError(ToolErrorCode.NOT_FOUND, f"{what} not found: {ref}")
    return payload


def crm_search_accounts(args: SearchAccountsArgs, context: ToolContext) -> JSONObject:
    return context.adapters.crm.search_accounts(
        query=args.query, segment=args.segment, limit=args.limit
    )


def crm_get_account(args: AccountRefArgs, context: ToolContext) -> JSONObject:
    payload = context.adapters.crm.get_account(account_ref=args.account_ref)
    return _require(payload, "account", args.account_ref)


def crm_get_opportunity(args: OpportunityRefArgs, context: ToolContext) -> JSONObject:
    payload = context.adapters.crm.get_opportunity(opportunity_ref=args.opportunity_ref)
    return _require(payload, "opportunity", args.opportunity_ref)


def crm_list_account_activities(args: ListActivitiesArgs, context: ToolContext) -> JSONObject:
    payload = context.adapters.crm.list_account_activities(
        account_ref=args.account_ref, since=args.since, limit=args.limit
    )
    return _require(payload, "account", args.account_ref)


def product_get_usage_summary(args: UsageSummaryArgs, context: ToolContext) -> JSONObject:
    payload = context.adapters.product.get_usage_summary(
        account_ref=args.account_ref,
        period_start=args.period_start,
        period_end=args.period_end,
    )
    return _require(payload, "account", args.account_ref)


def engagement_get_email_activity(args: EngagementArgs, context: ToolContext) -> JSONObject:
    payload = context.adapters.engagement.get_email_activity(
        account_ref=args.account_ref, since=args.since
    )
    return _require(payload, "account", args.account_ref)


def engagement_get_meeting_activity(args: EngagementArgs, context: ToolContext) -> JSONObject:
    payload = context.adapters.engagement.get_meeting_activity(
        account_ref=args.account_ref, since=args.since
    )
    return _require(payload, "account", args.account_ref)


def support_get_open_issues(args: AccountRefArgs, context: ToolContext) -> JSONObject:
    payload = context.adapters.support.get_open_issues(account_ref=args.account_ref)
    return _require(payload, "account", args.account_ref)


def enrichment_get_company_profile(args: AccountRefArgs, context: ToolContext) -> JSONObject:
    payload = context.adapters.enrichment.get_company_profile(account_ref=args.account_ref)
    return _require(payload, "company profile", args.account_ref)
