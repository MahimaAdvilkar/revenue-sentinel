"""Turning an approved intervention into tool arguments. Deterministically.

The model wrote a title and a rationale. It did **not** write the arguments, and this is
where that boundary is kept: the due date comes from the injected evaluation timestamp,
the assignee from the opportunity's owner, and the recipient from the account owner. None
of it is free text the model chose, because free text the model chose is free text an
injected instruction could have chosen (rule 14).

The model's prose does appear -- as the task description and the draft body. That is the
point of the feature. It is carried verbatim into a *data* field of a typed, validated
tool call, where the worst it can do is read badly. It never becomes an argument that
selects a target, an assignee, or a recipient.

Arguments are a pure function of persisted values, which is also what makes the
idempotency key stable: same intervention, same arguments, same key, forever.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import investigation as orm
from revenue_sentinel.domain.enums import ActionType
from revenue_sentinel.domain.gtm import Account, Opportunity

TASK_DUE_IN: Final = timedelta(days=2)
"""Two days from the evaluation timestamp -- soon enough to matter for a deal that has
been silent for fourteen, and derived from injected time so a replay is identical."""

DRAFT_INTENT: Final = "re_engagement"


class UnsupportedActionError(ValueError):
    """No argument builder for this action type."""


def build_arguments(
    intervention: orm.Intervention,
    *,
    action_type: ActionType,
    account: Account,
    opportunity: Opportunity,
    incident_ref: str,
    occurred_at: datetime,
) -> JSONObject:
    """The arguments for one authorised action. Same inputs, same output, always."""
    match action_type:
        case ActionType.CRM_TASK:
            return {
                "opportunity_ref": opportunity.opportunity_ref,
                "title": intervention.title,
                "description": intervention.rationale,
                "due_date": (occurred_at.date() + TASK_DUE_IN).isoformat(),
                "assignee_ref": opportunity.owner_id,
            }

        case ActionType.EMAIL_DRAFT:
            return {
                "account_ref": account.account_ref,
                "recipient_ref": account.owner_id,
                "subject": intervention.title,
                "body": intervention.rationale,
                "intent": DRAFT_INTENT,
            }

        case ActionType.SLACK_APPROVAL_REQUEST:
            return {
                "channel_ref": "#revenue-ops",
                "incident_ref": incident_ref,
                "summary": intervention.title,
            }

        case _:
            # `CRM_FIELD_UPDATE` lands here. `crm_update_opportunity` is registered and
            # policy-classified but deliberately unreachable in v1, and an action with
            # no argument builder cannot execute.
            raise UnsupportedActionError(
                f"{action_type.value} has no argument builder. It is not executable in v1."
            )
