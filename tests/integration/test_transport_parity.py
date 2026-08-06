"""Transport parity: stdio and in-process return the same thing.

A real subprocess, a real MCP initialization handshake, real JSON-RPC over pipes. Not
a simulation of a transport -- `docs/mcp-design.md` §5 says the stdio server is "the
real, spec-compliant thing", and this is what holds that claim to account.

Parity here is **structural before it is tested**: the stdio server's `tools/call`
handler and the in-process client both delegate to `dispatcher.dispatch`. There is no
second implementation that could drift. These tests confirm the wiring rather than
police two copies of the logic.

The subprocess talks to the same PostgreSQL the test session does, so these read tools
must be exercised against **committed** data. The seeded fixtures used elsewhere live
inside a rolled-back transaction the subprocess cannot see, which is why this module
commits its own scenario and cleans up afterwards.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.db.models import gtm as gtm_orm
from revenue_sentinel.db.seeding import seed_database
from revenue_sentinel.governance.stub import StubPolicyEngine
from revenue_sentinel.integrations.simulated.behaviour import SimulatedBehaviour
from revenue_sentinel.mcp.client import InProcessMcpClient
from revenue_sentinel.mcp.context import ToolContext, build_simulated_adapters
from revenue_sentinel.mcp.registry import EXPECTED_TOOL_COUNT

STDIO_TIMEOUT_SECONDS = 60


@pytest.fixture(scope="module")
def committed_scenario(engine: Engine) -> Iterator[None]:
    """Seed data the subprocess can actually see, then remove it.

    Module-scoped because launching a subprocess per test would make this file the
    slowest in the suite for no additional confidence.
    """
    from revenue_sentinel.core.config import get_settings

    settings = get_settings()
    with Session(engine) as setup:
        seed_database(setup, seed=settings.seed, evaluated_at=settings.evaluation_timestamp)
        setup.commit()

    yield

    with Session(engine) as teardown:
        for model in (
            gtm_orm.Activity,
            gtm_orm.UsageSnapshot,
            gtm_orm.EngagementEvent,
            gtm_orm.SupportIssue,
            gtm_orm.CompanyProfile,
            gtm_orm.Opportunity,
            gtm_orm.Account,
        ):
            teardown.execute(sa.delete(model))
        teardown.commit()


async def _over_stdio(calls: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """One subprocess, one handshake, N tool calls."""
    params = StdioServerParameters(command=sys.executable, args=["-m", "scripts.mcp_server"])

    async with (
        stdio_client(params) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialised = await session.initialize()
        listed = await session.list_tools()

        results: dict[str, Any] = {}
        for tool_name, arguments in calls:
            response = await session.call_tool(tool_name, arguments)
            results[tool_name] = {
                "payload": json.loads(response.content[0].text),
                "is_error": response.is_error,
            }

        return {
            "server_name": initialised.server_info.name,
            "protocol_version": str(initialised.protocol_version),
            "tools": listed.tools,
            "results": results,
        }


def over_stdio(calls: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    return asyncio.run(asyncio.wait_for(_over_stdio(calls), timeout=STDIO_TIMEOUT_SECONDS))


@pytest.fixture(scope="module")
def stdio_session(committed_scenario: None) -> dict[str, Any]:
    """A single real subprocess exchange, reused across the assertions below."""
    return over_stdio(
        [
            ("crm_get_account", {"account_ref": "ACC-1001"}),
            ("crm_get_opportunity", {"opportunity_ref": "OPP-2001"}),
            ("support_get_open_issues", {"account_ref": "ACC-1001"}),
        ]
    )


def in_process(session: Session, settings: Settings) -> InProcessMcpClient:
    context = ToolContext(
        session=session,
        adapters=build_simulated_adapters(session, SimulatedBehaviour()),
        occurred_at=settings.evaluation_timestamp,
        node_name="parity",
        policy=StubPolicyEngine(),
    )
    return InProcessMcpClient(context)


# ---------------------------------------------------------------------------
# The subprocess is real
# ---------------------------------------------------------------------------
def test_the_handshake_completes_against_a_real_subprocess(
    stdio_session: dict[str, Any],
) -> None:
    assert stdio_session["server_name"] == "revenue-sentinel-gtm"
    assert stdio_session["protocol_version"]


def test_all_fifteen_tools_are_advertised_over_stdio(stdio_session: dict[str, Any]) -> None:
    assert len(stdio_session["tools"]) == EXPECTED_TOOL_COUNT


def test_strict_schemas_survive_the_wire(stdio_session: dict[str, Any]) -> None:
    """`additionalProperties: false` is what a connecting client actually receives,
    not merely what the registry holds in memory."""
    for tool in stdio_session["tools"]:
        assert tool.input_schema["additionalProperties"] is False, tool.name


def test_no_send_email_tool_is_advertised(stdio_session: dict[str, Any]) -> None:
    names = {tool.name for tool in stdio_session["tools"]}
    assert not any("send_email" in name for name in names)


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("crm_get_account", {"account_ref": "ACC-1001"}),
        ("crm_get_opportunity", {"opportunity_ref": "OPP-2001"}),
        ("support_get_open_issues", {"account_ref": "ACC-1001"}),
    ],
)
def test_both_transports_return_identical_payloads(
    tool_name: str,
    arguments: dict[str, Any],
    stdio_session: dict[str, Any],
    committed_scenario: None,
    engine: Engine,
    settings: Settings,
) -> None:
    """The same registered handler, reached two ways."""
    with Session(engine) as session:
        local = in_process(session, settings).call_tool(tool_name, arguments)

    remote = stdio_session["results"][tool_name]["payload"]

    assert json.dumps(remote, sort_keys=True) == json.dumps(local, sort_keys=True)


def test_both_transports_advertise_the_same_catalog(
    stdio_session: dict[str, Any], engine: Engine, settings: Settings
) -> None:
    with Session(engine) as session:
        local_names = {tool["name"] for tool in in_process(session, settings).list_tools()}

    remote_names = {tool.name for tool in stdio_session["tools"]}
    assert local_names == remote_names


def test_the_simulated_status_is_carried_over_the_wire(stdio_session: dict[str, Any]) -> None:
    for tool_name in ("crm_get_account", "crm_get_opportunity", "support_get_open_issues"):
        assert stdio_session["results"][tool_name]["payload"]["integration_status"] == "SIMULATED"


def test_a_missing_entity_over_stdio_is_a_typed_error(committed_scenario: None) -> None:
    exchange = over_stdio([("crm_get_account", {"account_ref": "ACC-9999"})])
    result = exchange["results"]["crm_get_account"]

    assert result["is_error"] is True
    assert result["payload"]["error"]["code"] == "NOT_FOUND"
    assert result["payload"]["error"]["retry"] is False


def test_an_unknown_argument_is_rejected_over_stdio(committed_scenario: None) -> None:
    """Strictness is enforced by the server, not only advertised by it."""
    exchange = over_stdio(
        [("crm_get_account", {"account_ref": "ACC-1001", "definitely_not_a_field": 1})]
    )
    result = exchange["results"]["crm_get_account"]

    assert result["payload"]["error"]["code"] == "INVALID_ARGUMENTS"


# A stdio equivalent of "a write with no policy engine is refused" is deliberately
# absent. The guarantee itself is proven four ways in test_mcp_dispatch.py against the
# same dispatcher this transport delegates to. Over stdio the refusal surfaces as a
# server-side failure whose exact client-visible shape I did not pin down, and
# asserting a shape I have not verified would be worse than not asserting it.
# Open question for Session 5: should a missing engine be a typed POLICY_DENIED-style
# result over the wire, or stay a hard misconfiguration failure?
