"""Computation and audit -- Tier 0.

`analytics_calculate_pipeline_impact` is the rule-9 enforcement point. The Revenue
Analyst can *request* the calculation and cannot perform it: the tool takes inputs and
returns a figure, and there is no argument through which a model could supply one.
The arithmetic runs in `analytics/`, which `import-linter` R3 makes unreachable from
`intelligence/` and `agents/`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import sqlalchemy as sa

from revenue_sentinel.analytics.pipeline_impact import calculate_pipeline_impact
from revenue_sentinel.core.errors import CalculationError
from revenue_sentinel.core.ids import new_id
from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import gtm as gtm_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.mcp.context import ToolContext
from revenue_sentinel.mcp.errors import ToolErrorCode, ToolFailureError
from revenue_sentinel.mcp.schemas import AuditEventArgs, PipelineImpactArgs

AUDIT_ACTOR = "agent:via_mcp"


def analytics_calculate_pipeline_impact(
    args: PipelineImpactArgs, context: ToolContext
) -> JSONObject:
    opportunity = context.session.scalar(
        sa.select(gtm_orm.Opportunity).where(
            gtm_orm.Opportunity.opportunity_ref == args.opportunity_ref
        )
    )
    if opportunity is None:
        raise ToolFailureError(
            ToolErrorCode.NOT_FOUND, f"opportunity not found: {args.opportunity_ref}"
        )

    try:
        growth = Decimal(args.usage_growth)
    except (InvalidOperation, ValueError) as exc:
        raise ToolFailureError(
            ToolErrorCode.INVALID_ARGUMENTS,
            f"usage_growth must be a decimal ratio, got {args.usage_growth!r}",
        ) from exc

    try:
        impact = calculate_pipeline_impact(
            amount=opportunity.amount,
            currency=opportunity.currency,
            probability=opportunity.probability,
            days_inactive=args.days_inactive,
            stage=opportunity.stage,
            usage_growth=growth,
        )
    except CalculationError as exc:
        # The calculator refuses nonsense rather than returning a plausible zero.
        raise ToolFailureError(ToolErrorCode.INVALID_ARGUMENTS, str(exc)) from exc

    return {
        "opportunity_ref": args.opportunity_ref,
        "signal_type": args.signal_type,
        "currency": impact.currency,
        "pipeline_value": str(impact.pipeline_value),
        "weighted_value": str(impact.weighted_value),
        "at_risk_gross": str(impact.at_risk_gross),
        "at_risk_value": str(impact.at_risk_value),
        "stall_risk_factor": str(impact.applied_stall_risk_factor),
        "usage_offset": str(impact.applied_usage_offset),
        "method_version": impact.method_version,
        "bands_version": impact.bands_version,
        "computed_by": "deterministic",
        "inputs": impact.inputs,
    }


def audit_write_event(args: AuditEventArgs, context: ToolContext) -> JSONObject:
    incident = context.session.scalar(
        sa.select(workflow_orm.Incident).where(
            workflow_orm.Incident.incident_ref == args.incident_ref
        )
    )
    if incident is None:
        raise ToolFailureError(ToolErrorCode.NOT_FOUND, f"incident not found: {args.incident_ref}")

    event = obs_orm.AuditEvent(
        id=new_id(),
        run_id=context.run_id,
        incident_id=incident.id,
        event_type=args.event_type,
        actor=AUDIT_ACTOR,
        payload=args.payload,
        occurred_at=context.occurred_at,
    )
    context.session.add(event)
    context.session.flush()
    return {"recorded": True, "incident_ref": args.incident_ref, "event_type": args.event_type}
