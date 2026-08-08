"""The synchronous facade over an asynchronous protocol (ADR-0014).

MCP is async. This system is not (ADR-0009): repositories, agents, LangGraph nodes and
the whole test suite are synchronous. Rather than convert all of that, async is
confined to this one module, which owns a persistent `asyncio.Runner` and exposes a
plain synchronous `call_tool`.

`InProcessMcpClient` calls `dispatcher.dispatch` directly -- the same function the
stdio server's `tools/call` handler delegates to. Parity between transports is
therefore structural rather than something two code paths have to be kept in agreement
about, and the parity test verifies it rather than establishing it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import replace
from types import TracebackType
from typing import Any, Protocol, runtime_checkable

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.mcp.context import ToolContext
from revenue_sentinel.mcp.dispatcher import CallCounter, dispatch
from revenue_sentinel.mcp.registry import TOOL_SPECS


@runtime_checkable
class McpClient(Protocol):
    """A synchronous way to invoke a tool, whatever the transport."""

    def call_tool(self, tool_name: str, arguments: JSONObject) -> JSONObject: ...

    def list_tools(self) -> list[JSONObject]: ...


class InProcessMcpClient:
    """Calls the dispatcher directly. No subprocess, no sockets, no flake.

    This is what tests and the investigation graph use. It is not a mock of the
    server -- it is the server's own dispatch path, reached without a transport.
    """

    def __init__(self, context: ToolContext) -> None:
        self._context = context
        self._counter = CallCounter()

    def with_policy(self, engine: object) -> InProcessMcpClient:
        """A sibling client bound to a different policy engine.

        `execution/` uses this to hand the write gate the approval an action already
        has, without mutating this client and without the caller having to know how a
        `ToolContext` is assembled. Returning a new client rather than swapping a field
        means the narrower permission cannot outlive the one action it was built for.
        """
        return InProcessMcpClient(replace(self._context, policy=engine))  # type: ignore[arg-type]

    def call_tool(self, tool_name: str, arguments: JSONObject) -> JSONObject:
        return dispatch(tool_name, arguments, self._context, counter=self._counter)

    def list_tools(self) -> list[JSONObject]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
                "tier": int(spec.tier),
                "is_write": spec.is_write,
            }
            for spec in TOOL_SPECS
        ]


class AsyncBridge:
    """Owns one event loop for the life of the process.

    `asyncio.Runner` reuses a single loop across calls rather than creating and
    destroying one per invocation. It is only valid from synchronous code -- which is
    all this system has -- and raises rather than deadlocking if a loop is already
    running, which is the failure we would want to be loud.
    """

    def __init__(self) -> None:
        self._runner = asyncio.Runner()

    def run[T](self, coro: Coroutine[Any, Any, T]) -> T:
        return self._runner.run(coro)

    def close(self) -> None:
        self._runner.close()

    def __enter__(self) -> AsyncBridge:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
