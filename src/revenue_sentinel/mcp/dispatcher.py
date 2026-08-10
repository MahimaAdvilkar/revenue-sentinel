"""The one path every tool call takes.

    validate -> gate (writes only) -> adapter -> envelope -> ledger

Both transports call this function. The stdio server's `tools/call` handler is a thin
wrapper around it and the in-process client calls it directly, so **transport parity is
structural** rather than something two code paths have to be kept in agreement about.

Nothing here is optional. A handler cannot skip the gate, forget the envelope, or
avoid the ledger, because a handler never sees any of them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Final

from pydantic import ValidationError

from revenue_sentinel.core.logging import get_logger
from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.cost.ledger import record_tool_cost
from revenue_sentinel.domain.enums import ToolCallStatus
from revenue_sentinel.integrations.simulated.behaviour import InjectedFailureError
from revenue_sentinel.integrations.status import IntegrationStatus, status_of
from revenue_sentinel.mcp.context import ToolContext
from revenue_sentinel.mcp.envelope import error_envelope, success_envelope
from revenue_sentinel.mcp.errors import ToolErrorCode, ToolFailureError
from revenue_sentinel.mcp.gate import authorize_write
from revenue_sentinel.mcp.ledger import record_tool_call
from revenue_sentinel.mcp.registry import get_spec

logger = get_logger(__name__)

UNKNOWN_TOOL_STATUS: Final[IntegrationStatus] = "SIMULATED"

# Injected failure kinds map to the error codes an agent knows how to act on.
_INJECTED_TO_CODE: Final[dict[str, ToolErrorCode]] = {
    "RATE_LIMITED": ToolErrorCode.RATE_LIMITED,
    "ADAPTER_ERROR": ToolErrorCode.ADAPTER_ERROR,
    "BUDGET_EXCEEDED": ToolErrorCode.BUDGET_EXCEEDED,
}


@dataclass(slots=True)
class CallCounter:
    """Per-run ordinals, so span ids are stable across a replay."""

    counts: dict[str, int] = field(default_factory=dict)

    def next_for(self, tool_name: str) -> int:
        ordinal = self.counts.get(tool_name, 0) + 1
        self.counts[tool_name] = ordinal
        return ordinal


def dispatch(
    tool_name: str,
    arguments: JSONObject,
    context: ToolContext,
    *,
    counter: CallCounter | None = None,
) -> JSONObject:
    """Execute one tool call and return its envelope. Never raises for tool errors."""
    ordinal = (counter or CallCounter()).next_for(tool_name)
    started = time.perf_counter()

    spec = get_spec(tool_name)
    if spec is None:
        failure = ToolFailureError(
            ToolErrorCode.NOT_FOUND,
            f"no such tool: {tool_name}",
            detail={"available": [str(name) for name in sorted(_tool_names())]},
        )
        return error_envelope(
            tool=tool_name, integration_status=UNKNOWN_TOOL_STATUS, failure=failure
        )

    integration_status = status_of(context.adapters.modules[spec.adapter_key])
    result: JSONObject
    status: ToolCallStatus

    try:
        try:
            args = spec.args_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolFailureError(
                ToolErrorCode.INVALID_ARGUMENTS,
                f"arguments for {tool_name} failed validation",
                detail={"errors": [str(error) for error in exc.errors(include_url=False)]},
            ) from exc

        if spec.is_write:
            # No decision, no adapter. Enforced here, not in the handler.
            authorize_write(
                tool_name=tool_name,
                tier=spec.tier,
                arguments=arguments,
                engine=context.policy,
            )

        payload = spec.handler(args, context)
        result = success_envelope(
            tool=tool_name, integration_status=integration_status, data=payload
        )
        status = ToolCallStatus.SUCCESS

    except InjectedFailureError as exc:
        failure = ToolFailureError(
            _INJECTED_TO_CODE.get(exc.failure_kind, ToolErrorCode.ADAPTER_ERROR), str(exc)
        )
        result = error_envelope(
            tool=tool_name, integration_status=integration_status, failure=failure
        )
        status = ToolCallStatus.ERROR

    except ToolFailureError as exc:
        result = error_envelope(tool=tool_name, integration_status=integration_status, failure=exc)
        status = (
            ToolCallStatus.DENIED
            if exc.code
            in (
                ToolErrorCode.POLICY_DENIED,
                ToolErrorCode.APPROVAL_REQUIRED,
                # Nothing was executed, so the ledger must not call this a generic
                # error that a reader might mistake for a partial attempt.
                ToolErrorCode.POLICY_ENGINE_UNAVAILABLE,
            )
            else ToolCallStatus.ERROR
        )

    duration_ms = int((time.perf_counter() - started) * 1000)

    if context.run_id is not None:
        tool_call = record_tool_call(
            context.session,
            run_id=context.run_id,
            node_name=context.node_name,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            status=status,
            duration_ms=duration_ms,
            ordinal=ordinal,
        )
        # Always $0.000000 in v1 -- every adapter is SIMULATED and bills nothing. The
        # row is written anyway: an absent entry would be ambiguous between "free" and
        # "not recorded", which is the ambiguity a ledger exists to remove.
        record_tool_cost(
            context.session,
            run_id=context.run_id,
            tool_call_id=tool_call.id,
            occurred_at=context.occurred_at,
        )

    logger.info("tool_call", tool=tool_name, status=status.value, duration_ms=duration_ms)
    return result


def _tool_names() -> list[str]:
    from revenue_sentinel.mcp.registry import REGISTRY

    return list(REGISTRY)
