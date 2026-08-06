"""The GTM MCP server.

Built on `mcp.server.lowlevel.Server` rather than the ergonomic `MCPServer`, for one
specific reason: `docs/mcp-design.md` §4 requires every tool to publish a schema with
`additionalProperties: false`, and the ergonomic decorator does not emit it **and
silently accepts unknown arguments**. Verified by probe before choosing. The low-level
server lets us publish exactly the schema in `registry.py` and receive the raw argument
dict, so our `extra="forbid"` models do the real rejecting.

Both request handlers are thin. `tools/list` renders the registry; `tools/call`
delegates to `dispatcher.dispatch` -- the same function the in-process client calls,
so the two transports cannot drift.
"""

from __future__ import annotations

import json
from typing import Final

import mcp.types as mcp_types
from mcp.server.lowlevel import Server

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.mcp.context import ToolContext
from revenue_sentinel.mcp.dispatcher import CallCounter, dispatch
from revenue_sentinel.mcp.registry import TOOL_SPECS

SERVER_NAME: Final = "revenue-sentinel-gtm"
SERVER_INSTRUCTIONS: Final = (
    "Narrow, typed GTM tools. All integrations are SIMULATED; every result carries "
    "integration_status. Write tools require a policy decision. A POLICY_DENIED "
    "result must not be routed around."
)


def published_tools() -> list[mcp_types.Tool]:
    """The catalog, exactly as `registry.py` declares it."""
    return [
        mcp_types.Tool(
            name=spec.name,
            description=spec.description,
            inputSchema=spec.input_schema,
        )
        for spec in TOOL_SPECS
    ]


def build_server(context: ToolContext) -> Server:
    """A spec-compliant MCP server bound to one tool context."""
    server = Server(SERVER_NAME)
    counter = CallCounter()

    async def handle_list(request_context: object, params: object) -> mcp_types.ListToolsResult:
        return mcp_types.ListToolsResult(tools=published_tools())

    async def handle_call(
        request_context: object, params: mcp_types.CallToolRequestParams
    ) -> mcp_types.CallToolResult:
        envelope: JSONObject = dispatch(
            params.name, dict(params.arguments or {}), context, counter=counter
        )
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=json.dumps(envelope, default=str))],
            isError=not envelope.get("ok", False),
        )

    server.add_request_handler("tools/list", mcp_types.PaginatedRequestParams, handle_list)
    server.add_request_handler("tools/call", mcp_types.CallToolRequestParams, handle_call)
    return server
