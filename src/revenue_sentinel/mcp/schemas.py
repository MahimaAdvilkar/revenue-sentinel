"""Argument models -- one per tool, every one strict.

`extra="forbid"` is the enforcement. It matters more here than anywhere else in the
codebase, because these models are the boundary an LLM writes to: an unexpected key is
either a misunderstanding or an attempt, and silently dropping it hides both.

`strict_schema()` produces the published JSON Schema and **asserts**
`additionalProperties: false`. That assertion is not decorative -- the MCP SDK's own
tool decorator omits it and silently accepts unknown arguments, which is why this layer
publishes and validates its own schemas rather than delegating either.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum, unique
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from revenue_sentinel.core.types import JSONObject

MAX_SEARCH_RESULTS: Final = 50
MAX_ACTIVITY_RESULTS: Final = 200

AccountRefArg = Annotated[str, StringConstraints(pattern=r"^ACC-[0-9]{4}$")]
OpportunityRefArg = Annotated[str, StringConstraints(pattern=r"^OPP-[0-9]{4}$")]
IncidentRefArg = Annotated[str, StringConstraints(pattern=r"^INC-[0-9]{3}$")]
UserRefArg = Annotated[str, StringConstraints(pattern=r"^USR-[0-9]{1,4}$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class ToolArgs(BaseModel):
    """Base for every tool's arguments: immutable and closed."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def strict_schema(model: type[ToolArgs]) -> JSONObject:
    """The published schema, with strictness verified rather than assumed."""
    schema: JSONObject = dict(model.model_json_schema())
    if schema.get("additionalProperties") is not False:
        raise ValueError(
            f"{model.__name__} must produce additionalProperties: false; "
            f"check that it inherits ToolArgs and keeps extra='forbid'"
        )
    return schema


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------
class SearchAccountsArgs(ToolArgs):
    query: ShortText
    segment: str | None = None
    limit: int = Field(default=10, ge=1, le=MAX_SEARCH_RESULTS)


class AccountRefArgs(ToolArgs):
    account_ref: AccountRefArg


class OpportunityRefArgs(ToolArgs):
    opportunity_ref: OpportunityRefArg


class ListActivitiesArgs(ToolArgs):
    account_ref: AccountRefArg
    since: datetime
    limit: int = Field(default=50, ge=1, le=MAX_ACTIVITY_RESULTS)


class UsageSummaryArgs(ToolArgs):
    account_ref: AccountRefArg
    period_start: date
    period_end: date


class EngagementArgs(ToolArgs):
    account_ref: AccountRefArg
    since: datetime


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------
class CreateTaskArgs(ToolArgs):
    opportunity_ref: OpportunityRefArg
    title: ShortText
    description: LongText
    due_date: date
    assignee_ref: UserRefArg


@unique
class UpdatableField(StrEnum):
    """The fields `crm_update_opportunity` may touch.

    A closed set, so "is this a material CRM change?" is decidable from the arguments
    alone rather than from a judgement call at policy time (`security-model.md` §3).
    """

    AMOUNT = "amount"
    STAGE = "stage"
    PROBABILITY = "probability"
    EXPECTED_CLOSE_DATE = "expected_close_date"
    OWNER_ID = "owner_id"
    DESCRIPTION = "description"


class UpdateOpportunityArgs(ToolArgs):
    opportunity_ref: OpportunityRefArg
    field_name: UpdatableField
    value: ShortText
    reason: LongText


class CreateEmailDraftArgs(ToolArgs):
    account_ref: AccountRefArg
    recipient_ref: UserRefArg
    subject: ShortText
    body: LongText
    intent: ShortText


class SlackApprovalArgs(ToolArgs):
    channel_ref: ShortText
    incident_ref: IncidentRefArg
    summary: LongText


# ---------------------------------------------------------------------------
# Computation and audit
# ---------------------------------------------------------------------------
class PipelineImpactArgs(ToolArgs):
    """The rule-9 enforcement point.

    The analyst supplies the *inputs* and receives the *figure*. It cannot supply the
    figure, because there is no field for one.
    """

    opportunity_ref: OpportunityRefArg
    signal_type: ShortText
    days_inactive: int = Field(ge=0, le=3650)
    usage_growth: str


class AuditEventArgs(ToolArgs):
    incident_ref: IncidentRefArg
    event_type: ShortText
    payload: JSONObject
