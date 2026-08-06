"""Tool result envelopes.

Every result -- success or failure -- carries `integration_status`, read from the
adapter module that served the request rather than hardcoded here (ADR-0004
commitment 2). The dashboard's SIMULATED badge is therefore derived from the code that
actually ran.
"""

from __future__ import annotations

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.integrations.status import IntegrationStatus
from revenue_sentinel.mcp.errors import ToolFailureError


def success_envelope(
    *, tool: str, integration_status: IntegrationStatus, data: JSONObject
) -> JSONObject:
    return {"tool": tool, "ok": True, "integration_status": integration_status, "data": data}


def error_envelope(
    *, tool: str, integration_status: IntegrationStatus, failure: ToolFailureError
) -> JSONObject:
    policy = failure.policy
    return {
        "tool": tool,
        "ok": False,
        "integration_status": integration_status,
        "error": {
            "code": failure.code.value,
            "message": failure.message,
            "retry": policy.retry,
            "alternative_route": policy.alternative_route,
            "guidance": policy.guidance,
            "detail": failure.detail,
        },
    }
