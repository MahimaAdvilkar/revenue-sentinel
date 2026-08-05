"""Investigation Planner -- LLM-backed.

Given an incident, produces an ordered plan naming which evidence sources to consult
and why. Genuine reasoning over ambiguous context: which of five sources matter for
*this* incident, and in what order.

A pure function of its inputs and its injected client. No database, no clock, no
configuration read from the environment -- which is what lets it be tested with a
stub client and no graph running.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from revenue_sentinel.domain.gtm import Account, Opportunity
from revenue_sentinel.domain.incidents import Incident
from revenue_sentinel.intelligence.ports import LLMClient, LLMRequest, LLMResponse
from revenue_sentinel.intelligence.prompts import PLANNER_SYSTEM_PROMPT, render_incident_context
from revenue_sentinel.intelligence.schemas import InvestigationPlan

NODE_NAME = "plan_investigation"


@dataclass(frozen=True, slots=True)
class PlanningInput:
    """Everything the planner may see. Assembled by the caller, not fetched here."""

    incident: Incident
    account: Account
    opportunity: Opportunity
    days_inactive: int
    usage_growth: Decimal


def plan_investigation(
    planning_input: PlanningInput, *, llm: LLMClient, model_id: str, effort: str
) -> LLMResponse[InvestigationPlan]:
    """Ask the planner for an ordered plan.

    Returns the whole `LLMResponse` rather than just the plan so the caller can record
    the model call. An agent that discarded that metadata would make the cost ledger
    and the "which agents used a model" proof impossible to build.
    """
    user_content = render_incident_context(
        incident_ref=planning_input.incident.incident_ref,
        incident_type=planning_input.incident.incident_type.value,
        severity=planning_input.incident.severity.value,
        account_name=planning_input.account.name,
        opportunity_ref=planning_input.opportunity.opportunity_ref,
        opportunity_name=planning_input.opportunity.name,
        stage=planning_input.opportunity.stage.value,
        amount=str(planning_input.opportunity.amount),
        currency=planning_input.opportunity.currency,
        days_inactive=planning_input.days_inactive,
        usage_growth=str(planning_input.usage_growth),
    )

    return llm.complete_structured(
        LLMRequest(
            node_name=NODE_NAME,
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_content=user_content,
            output_schema=InvestigationPlan,
            model_id=model_id,
            effort=effort,
        )
    )
