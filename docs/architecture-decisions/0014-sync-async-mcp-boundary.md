# ADR-0014: The synchronous/asynchronous boundary sits inside `mcp/client.py`

**Status:** Accepted
**Date:** 2026-08-05
**Deciders:** Mahima Advilkar

## Context

The MCP Python SDK is asynchronous to its foundations. `ClientSession`, `stdio_client`,
`Server.run`, and every request handler are coroutines; there is no synchronous client in
the package and none is planned. Session 4 had to connect that library to a codebase that
is synchronous by an explicit prior decision.

That decision is [ADR-0009](0009-synchronous-persistence.md): synchronous SQLAlchemy 2.0
throughout `db/`, synchronous `Session`, synchronous Alembic, `def` route handlers served
from Starlette's threadpool. Sessions 1 through 3 were built on it. Repositories, the
seeder, the CLI, the agents, the LangGraph nodes, the transition recorder, and all 730
tests are synchronous today.

So there are two languages in the same process, and the only real question is where the
seam between them goes. Three properties made that placement worth an ADR rather than a
reflex:

1. **The seam is contagious in one direction.** `async def` propagates upward through
   every caller. Put the boundary too high and `run_investigation`, the graph nodes, the
   agents, and every test fixture become `async` — which is a rewrite of the codebase to
   accommodate a transport.
2. **The failure mode is quiet.** A synchronous database call made from inside a running
   event loop does not raise. It blocks the loop, and it surfaces as a stall under load
   rather than as a red test. ADR-0009 named this as the specific bug class it was
   avoiding; introducing async carelessly would reintroduce it.
3. **The in-process path does not need async at all.** The dispatcher is an ordinary
   synchronous function. Async is a property of the *transport*, not of the tool logic.

## Decision

**Async is confined to `src/revenue_sentinel/mcp/client.py` and the stdio entry point
`scripts/mcp_server.py`. Nothing else in the codebase is a coroutine.**

Concretely:

- `mcp/client.py` owns `AsyncBridge`, which holds a single persistent
  `asyncio.Runner` for the life of the process and exposes `run(coro) -> T`. One loop is
  created and reused, rather than a new loop per call. `asyncio.Runner.run` is valid only
  from synchronous code and **raises rather than deadlocking** if a loop is already
  running — the loud failure is the point.
- `McpClient` is a synchronous `Protocol`: `call_tool(name, arguments) -> JSONObject` and
  `list_tools() -> list[JSONObject]`. No caller of the port ever sees a coroutine.
- `InProcessMcpClient` — the implementation the investigation graph uses — calls
  `dispatcher.dispatch` **directly**. It touches no event loop at all, so the default path
  through the system is not merely synchronous at the surface: it is synchronous all the
  way down.
- `scripts/mcp_server.py` is an `asyncio.run(serve())` process boundary. Async begins and
  ends inside that subprocess.
- Agents, LangGraph nodes, repositories, application services, the CLI, and the FastAPI
  routes remain synchronous, unchanged by Session 4.

**Both transports delegate to the same `dispatcher.dispatch`.** The stdio server's
`tools/call` handler and `InProcessMcpClient.call_tool` reach the identical function with
the identical `ToolContext`. Validation, the policy gate, the adapter call, the result
envelope, and the `tool_calls` ledger row all happen in one place. Transport parity is
therefore **structural** — there is no second implementation that could drift — and
`tests/integration/test_transport_parity.py` verifies that property rather than
establishing it.

That test now runs a real subprocess: `stdio_client` launches `python -m
scripts.mcp_server`, completes the MCP initialization handshake (`revenue-sentinel-gtm`,
protocol `2025-11-25`), lists 15 tools, confirms `additionalProperties: false` on every
schema as received over the wire, and exercises a successful read plus typed `NOT_FOUND`
and `INVALID_ARGUMENTS` errors. Three tools return payloads byte-identical to the
in-process client's. **The stdio proof exists and passes.** This decision is not being
recorded on the strength of an argument about how the transport would behave.

## Alternatives considered

**Convert the application to async.** Rejected. It reverses ADR-0009 for a transport
concern, touches every repository, node, fixture, and test, and reintroduces the
sync-call-in-event-loop bug class into a codebase that had designed it out. The MCP client
is not the bottleneck; nothing about this workload asks for concurrency.

**Wrap each call in `asyncio.run()`.** Rejected. It creates and tears down an event loop
per tool call. Correct but wasteful, and it silently defeats any connection or session
state a future stdio-backed client would want to hold across calls — which is precisely
what `AsyncBridge` exists to preserve.

**Run the async client on a dedicated background thread with a persistent loop, and
marshal calls in via `run_coroutine_threadsafe`.** Rejected as premature. It is the right
shape *if* synchronous code ever has to call MCP from inside an already-running event
loop — a FastAPI `async def` handler, say. Nothing does that today, and the machinery
(thread lifecycle, shutdown ordering, exception marshalling) is real complexity bought
against a hypothetical. `asyncio.Runner` raising in exactly that situation is the signal
that would justify building it.

**Make the in-process client go through the MCP protocol too, for uniformity.** Rejected.
It would add a transport, a serialization round-trip, and an event loop to the path the
graph and the entire test suite use, in exchange for a symmetry that buys nothing.
Dispatching directly is both faster and a shorter distance from a test failure to the code
that caused it.

## Consequences

**Easier.** The investigation graph is untouched by Session 4 — `McpEvidenceSource`
replaced `RepositoryEvidenceSource` behind the unchanged `EvidenceSource` port, and the
evidence is byte-identical. Tests stay synchronous and fast: no `pytest-asyncio` for
anything except the transport-parity module, which needs a subprocess anyway. Stack traces
from tool failures are readable, because there is no loop between the assertion and the
adapter.

**Harder.** There are now two ways to reach a tool, and a contributor could add logic to
the stdio handler instead of the dispatcher. The parity test is the guard, and it fails on
payload divergence rather than merely on a missing tool name.

**We now owe** one rule, and it is the mirror of ADR-0009's: **`AsyncBridge.run` must
never be called from inside a running event loop.** It will raise rather than deadlock, so
the violation is loud — but the fix at that point is the background-thread alternative
above, not a `nest_asyncio` patch.

**Also owed:** the stdio server currently binds `policy=None`, so a write attempted over
that transport raises rather than executing. The client-visible shape of that refusal is
**not yet pinned by a subprocess test** — asserting a shape that had not been verified
would have been worse than leaving it unasserted. The guarantee itself is proven four ways
in-process against the same dispatcher. Pinning the wire shape is Session 5 work, alongside
the real policy engine.

## Reversibility

This boundary is cheap to move, in both directions, and that is a deliberate property
rather than a hope:

- **The surface is one file.** Async appears in `mcp/client.py` and in the
  `asyncio.run(serve())` line of `scripts/mcp_server.py`. Nothing else in `src/` contains
  `async def` or `await`.
- **The port is synchronous and narrow.** `McpClient` has two methods. Adding an
  `AsyncMcpClient` alongside it — for a caller that genuinely lives on an event loop —
  requires no change to `InProcessMcpClient`, the dispatcher, the tools, or the adapters.
- **The logic is not on the async side.** Because both transports delegate to
  `dispatcher.dispatch`, moving the boundary relocates plumbing, not behaviour. There is no
  tool implementation that would have to be rewritten in a different colour.
- **The escape hatch is already designed.** Switching `AsyncBridge` from
  `asyncio.Runner` to a persistent background-thread loop is a change to one class, behind
  the same `run(coro) -> T` signature.

What is *not* cheap is the opposite move — converting the application to async — and that
is exactly the cost ADR-0009 chose to avoid and this ADR preserves.

## Revisit when

Any one of these is observed:

1. **`AsyncBridge.run` raises `RuntimeError: asyncio.run() cannot be called from a running
   event loop`** in normal operation — meaning a caller now lives on a loop. Move to the
   background-thread bridge; do not patch the loop.
2. **A remote MCP transport is added** (HTTP/SSE to a server outside this process), where
   connection setup, retries, and streaming make per-call loop entry genuinely expensive.
3. **Concurrent workflow runs become real** (`docs/scaling-roadmap.md`), *and* measurement
   shows threadpool saturation — the same trigger ADR-0009 names, since both decisions
   would then be revisited together rather than separately.
4. **A third transport appears**, at which point "both transports share one dispatcher"
   should be re-checked as an invariant rather than assumed.
