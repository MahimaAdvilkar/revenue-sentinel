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

Two things about the child process are stated explicitly rather than inherited, because
CI proved that inheriting them does not work:

* **`stdio_client` does not forward the parent environment.** It starts the server with a
  deliberately minimal one. On a developer machine the child still found its
  configuration in the repository's `.env` file; on CI, where configuration lives in
  environment variables and no `.env` exists, it died during startup with
  `ValidationError: database_url Field required`. The child's environment is now derived
  from the resolved `Settings`, so it is configured identically whichever source the
  parent read.
* **The child is pointed at the *test* database.** It previously used
  `settings.database_url` -- the development database -- while `committed_scenario` seeded
  the test database. The payloads matched only because both had been seeded from the same
  deterministic seed, which made the parity assertion accidental rather than earned.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import PROJECT_ROOT, Settings
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import gtm as gtm_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.seeding import seed_database
from revenue_sentinel.domain.enums import ToolCallStatus
from revenue_sentinel.governance.stub import DenyAllPolicyEngine, StubPolicyEngine
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


def server_environment(database_url: str, settings: Settings) -> dict[str, str]:
    """The child's configuration, stated rather than inherited.

    Deliberately narrow. `ANTHROPIC_API_KEY` is **not** passed, so the server cannot make
    a model call even on a developer machine whose environment holds a key -- the offline
    guarantee does not depend on the developer's shell being clean.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "DATABASE_URL": database_url,
        "APP_ENV": settings.app_env,
        "DEMO_MODE": settings.demo_mode,
        "SEED": str(settings.seed),
        "EVALUATION_TIMESTAMP": settings.evaluation_timestamp.isoformat(),
    }


async def _over_stdio(
    calls: list[tuple[str, dict[str, Any]]], environment: dict[str, str]
) -> dict[str, Any]:
    """One subprocess, one handshake, N tool calls."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "scripts.mcp_server"],
        env=environment,
        cwd=str(PROJECT_ROOT),
    )

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


def over_stdio(
    calls: list[tuple[str, dict[str, Any]]], environment: dict[str, str]
) -> dict[str, Any]:
    return asyncio.run(
        asyncio.wait_for(_over_stdio(calls, environment), timeout=STDIO_TIMEOUT_SECONDS)
    )


@pytest.fixture(scope="module")
def server_env(migrated_database_url: str, settings: Settings) -> dict[str, str]:
    """Points the subprocess at the **test** database -- the one the fixture seeds."""
    return server_environment(migrated_database_url, settings)


@pytest.fixture(scope="module")
def stdio_session(committed_scenario: None, server_env: dict[str, str]) -> dict[str, Any]:
    """A single real subprocess exchange, reused across the assertions below."""
    return over_stdio(
        [
            ("crm_get_account", {"account_ref": "ACC-1001"}),
            ("crm_get_opportunity", {"opportunity_ref": "OPP-2001"}),
            ("support_get_open_issues", {"account_ref": "ACC-1001"}),
        ],
        server_env,
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


def test_a_missing_entity_over_stdio_is_a_typed_error(
    committed_scenario: None, server_env: dict[str, str]
) -> None:
    exchange = over_stdio([("crm_get_account", {"account_ref": "ACC-9999"})], server_env)
    result = exchange["results"]["crm_get_account"]

    assert result["is_error"] is True
    assert result["payload"]["error"]["code"] == "NOT_FOUND"
    assert result["payload"]["error"]["retry"] is False


def test_an_unknown_argument_is_rejected_over_stdio(
    committed_scenario: None, server_env: dict[str, str]
) -> None:
    """Strictness is enforced by the server, not only advertised by it."""
    exchange = over_stdio(
        [("crm_get_account", {"account_ref": "ACC-1001", "definitely_not_a_field": 1})],
        server_env,
    )
    result = exchange["results"]["crm_get_account"]

    assert result["payload"]["error"]["code"] == "INVALID_ARGUMENTS"


# ---------------------------------------------------------------------------
# The missing-policy-engine refusal, pinned over the wire (Session 11)
# ---------------------------------------------------------------------------
# This was deliberately unasserted through Sessions 4-10, with an honest note saying the
# client-visible shape had not been pinned down. It was measured before being changed:
# the refusal escaped `dispatch` as a bare `MissingPolicyEngineError`, and the SDK turned
# it into a protocol-level `MCPError` -- no envelope, no code, no `integration_status`,
# and nothing a client could use to tell a misconfigured server from a crashed one. It
# failed closed, which was right, and it said nothing, which was not.
#
# It is now a typed `POLICY_ENGINE_UNAVAILABLE` envelope, distinct from `POLICY_DENIED`
# because a denial is a decision about the request and this is a deployment fault.
WRITE_CALL: tuple[str, dict[str, Any]] = (
    "crm_create_task",
    {
        "opportunity_ref": "OPP-2001",
        "title": "parity probe",
        "description": "must never reach an adapter",
        "due_date": "2026-08-15",
        "assignee_ref": "USR-1",
    },
)


class SpyCrmAdapter:
    """Records any call. The point is that it records none."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def _record(*_: object, **__: object) -> None:
            self.calls.append(name)
            raise AssertionError(f"adapter.{name} was reached despite no policy engine")

        return _record


def _unpoliced_in_process(
    session: Session, settings: Settings, *, run_id: UUID | None = None
) -> tuple[Any, SpyCrmAdapter]:
    """An in-process client with **no** policy engine and a spy CRM adapter.

    `run_id` is optional because the ledger only writes when a run is bound -- which is
    the same reason the stdio server, which has no run, writes nothing. The ledger
    assertion below binds one so there is a row to inspect.
    """
    spy = SpyCrmAdapter()
    adapters = build_simulated_adapters(session, SimulatedBehaviour())
    context = ToolContext(
        session=session,
        adapters=replace(adapters, crm=spy),
        occurred_at=settings.evaluation_timestamp,
        node_name="parity",
        run_id=run_id,
        policy=None,
    )
    return InProcessMcpClient(context), spy


def test_a_write_with_no_policy_engine_is_a_typed_error_over_stdio(
    committed_scenario: None, server_env: dict[str, str]
) -> None:
    """`scripts/mcp_server.py` binds `policy=None` deliberately, so this is the real path."""
    result = over_stdio([WRITE_CALL], server_env)["results"]["crm_create_task"]

    assert result["is_error"] is True
    error = result["payload"]["error"]
    assert error["code"] == "POLICY_ENGINE_UNAVAILABLE"
    assert error["code"] != "POLICY_DENIED", "a deployment fault is not a policy decision"
    assert error["retry"] is False
    assert error["alternative_route"] is False
    assert error["detail"] == {
        "tool": "crm_create_task",
        "tier": 1,
        "reason": "no_policy_engine_bound",
    }
    assert result["payload"]["ok"] is False
    assert result["payload"]["integration_status"] == "SIMULATED"


def test_the_refusal_is_identical_in_process_and_over_stdio(
    committed_scenario: None,
    server_env: dict[str, str],
    seeded_session: Session,
    settings: Settings,
) -> None:
    """Payload equality, the same assertion the successful reads get."""
    client, _ = _unpoliced_in_process(seeded_session, settings)
    name, arguments = WRITE_CALL
    local = client.call_tool(name, arguments)
    remote = over_stdio([WRITE_CALL], server_env)["results"]["crm_create_task"]["payload"]

    assert local == remote


def test_the_adapter_is_never_reached(seeded_session: Session, settings: Settings) -> None:
    """The gate runs before the handler, so the write never touches an adapter."""
    client, spy = _unpoliced_in_process(seeded_session, settings)
    name, arguments = WRITE_CALL

    envelope = client.call_tool(name, arguments)

    assert envelope["ok"] is False
    assert spy.calls == []


def test_the_ledger_records_the_refusal_and_claims_no_success(
    investigated: Any, seeded_session: Session, settings: Settings
) -> None:
    """A refused write must be recorded as refused -- never as a success, never as a
    generic error a reader could mistake for a partial attempt."""
    before_actions = seeded_session.scalar(
        sa.select(sa.func.count()).select_from(gov_orm.ActionRecord)
    )
    # The golden run already executed a successful `crm_create_task`, so the refusal is
    # identified by *which row is new* rather than by ordering -- UUIDs are not
    # chronological and `created_at` is the transaction timestamp.
    before_calls = set(seeded_session.scalars(sa.select(obs_orm.ToolCall.id)).all())

    client, _ = _unpoliced_in_process(seeded_session, settings, run_id=investigated.run_id)
    name, arguments = WRITE_CALL

    client.call_tool(name, arguments)

    call = seeded_session.scalars(
        sa.select(obs_orm.ToolCall).where(obs_orm.ToolCall.id.not_in(before_calls))
    ).one()
    assert call.tool_name == "crm_create_task"
    assert call.status is ToolCallStatus.DENIED
    assert call.status is not ToolCallStatus.SUCCESS
    # And no action record was created, let alone a succeeded one.
    assert (
        seeded_session.scalar(sa.select(sa.func.count()).select_from(gov_orm.ActionRecord))
        == before_actions
    )


def test_policy_denied_and_approval_required_are_unchanged(
    seeded_session: Session, settings: Settings
) -> None:
    """The new code must not have absorbed the two refusals that already existed."""
    context = ToolContext(
        session=seeded_session,
        adapters=build_simulated_adapters(seeded_session, SimulatedBehaviour()),
        occurred_at=settings.evaluation_timestamp,
        node_name="parity",
        policy=DenyAllPolicyEngine(),
    )
    name, arguments = WRITE_CALL

    envelope = InProcessMcpClient(context).call_tool(name, arguments)

    assert envelope["error"]["code"] == "POLICY_DENIED"
    assert envelope["error"]["retry"] is False
