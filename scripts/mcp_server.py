"""`make mcp` -- run the GTM MCP server over stdio.

A real subprocess speaking the MCP protocol, not a function registry. It builds its
own database session and adapter bundle, then serves the same handlers the in-process
client dispatches to.

`policy=None` is deliberate: the stdio server exposes read tools to any connected
client, and a write invoked over this transport must raise rather than execute. The
real policy engine arrives in Session 5.
"""

from __future__ import annotations

import asyncio

from mcp.server.stdio import stdio_server

from revenue_sentinel.core.config import get_settings
from revenue_sentinel.db.session import build_engine, build_session_factory
from revenue_sentinel.integrations.simulated.behaviour import SimulatedBehaviour
from revenue_sentinel.mcp.context import ToolContext, build_simulated_adapters
from revenue_sentinel.mcp.server import build_server


async def serve() -> None:
    settings = get_settings()
    session = build_session_factory(build_engine(settings))()
    behaviour = SimulatedBehaviour.from_settings(latency_ms=0, failure_script="")

    context = ToolContext(
        session=session,
        adapters=build_simulated_adapters(session, behaviour),
        occurred_at=settings.evaluation_timestamp,
        node_name="stdio",
        run_id=None,
        policy=None,
    )
    server = build_server(context)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(serve())
