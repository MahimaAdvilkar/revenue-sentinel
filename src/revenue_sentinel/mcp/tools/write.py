"""The four write tools.

**None of these is reachable without a policy decision.** The gate runs in the
dispatcher before a handler here is called, so these functions can be read as "what
happens once it is allowed" rather than having to re-check anything.

There is no `messaging_send_email`. Sending is Tier 3 -- not a capability this system
has, and not a tool that exists and gets denied.
"""

from __future__ import annotations

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.mcp.context import ToolContext
from revenue_sentinel.mcp.schemas import (
    CreateEmailDraftArgs,
    CreateTaskArgs,
    SlackApprovalArgs,
    UpdateOpportunityArgs,
)


def crm_create_task(args: CreateTaskArgs, context: ToolContext) -> JSONObject:
    """Tier 1 -- internal, reversible, no customer contact."""
    return context.adapters.crm.create_task(
        opportunity_ref=args.opportunity_ref,
        title=args.title,
        description=args.description,
        due_date=args.due_date,
        assignee_ref=args.assignee_ref,
    )


def crm_update_opportunity(args: UpdateOpportunityArgs, context: ToolContext) -> JSONObject:
    """Tier 2 -- a material CRM change on the forecast fields."""
    return context.adapters.crm.update_opportunity(
        opportunity_ref=args.opportunity_ref,
        field_name=args.field_name.value,
        value=args.value,
        reason=args.reason,
    )


def messaging_create_email_draft(args: CreateEmailDraftArgs, context: ToolContext) -> JSONObject:
    """Tier 2 -- customer-facing. Creates a draft. Sends nothing."""
    return context.adapters.messaging.create_email_draft(
        account_ref=args.account_ref,
        recipient_ref=args.recipient_ref,
        subject=args.subject,
        body=args.body,
        intent=args.intent,
    )


def messaging_send_slack_approval(args: SlackApprovalArgs, context: ToolContext) -> JSONObject:
    """Tier 1 -- an internal notification, no customer contact."""
    return context.adapters.messaging.send_slack_approval(
        channel_ref=args.channel_ref,
        incident_ref=args.incident_ref,
        summary=args.summary,
    )
