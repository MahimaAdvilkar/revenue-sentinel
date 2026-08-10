"""The dispatcher: validation, the write gate, the ledger, and injected failure.

Every tool call takes one path -- validate, gate, adapter, envelope, ledger -- so this
file exercises that path rather than each handler in isolation. A handler cannot skip
any of it, because a handler never sees any of it.

The assertions that carry the most weight:

* **A write with no policy engine raises.** Not "allows by default", not "warns".
* **A denied write never reaches its adapter**, proven with a spy rather than inferred
  from the returned error.
* **`POLICY_DENIED` is machine-readably un-reroutable**, because an agent that answers
  a refusal by trying another tool is what this layer exists to prevent.
* **Every result carries `SIMULATED`**, read from the adapter module rather than
  hardcoded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import ToolCallStatus
from revenue_sentinel.governance.stub import DenyAllPolicyEngine, StubPolicyEngine
from revenue_sentinel.integrations.simulated.behaviour import (
    SimulatedBehaviour,
    parse_failure_script,
)
from revenue_sentinel.mcp.context import ToolContext, build_simulated_adapters
from revenue_sentinel.mcp.dispatcher import CallCounter, dispatch
from revenue_sentinel.mcp.errors import ToolErrorCode
from revenue_sentinel.mcp.registry import REGISTRY, TOOL_SPECS

FAR_PAST = datetime(1970, 1, 1, tzinfo=UTC).isoformat()

# One valid argument set per tool, so every registered tool is actually exercised.
HAPPY_ARGS: dict[str, dict[str, Any]] = {
    "crm_search_accounts": {"query": "Northwind", "limit": 5},
    "crm_get_account": {"account_ref": "ACC-1001"},
    "crm_get_opportunity": {"opportunity_ref": "OPP-2001"},
    "crm_list_account_activities": {"account_ref": "ACC-1001", "since": FAR_PAST, "limit": 10},
    "product_get_usage_summary": {
        "account_ref": "ACC-1001",
        "period_start": "1970-01-01",
        "period_end": "2999-12-31",
    },
    "engagement_get_email_activity": {"account_ref": "ACC-1001", "since": FAR_PAST},
    "engagement_get_meeting_activity": {"account_ref": "ACC-1001", "since": FAR_PAST},
    "support_get_open_issues": {"account_ref": "ACC-1001"},
    "enrichment_get_company_profile": {"account_ref": "ACC-1001"},
    "crm_create_task": {
        "opportunity_ref": "OPP-2001",
        "title": "Re-engage",
        "description": "usage-based talk track",
        "due_date": "2026-08-10",
        "assignee_ref": "USR-77",
    },
    "crm_update_opportunity": {
        "opportunity_ref": "OPP-2001",
        "field_name": "stage",
        "value": "negotiation",
        "reason": "buyer re-engaged",
    },
    "messaging_create_email_draft": {
        "account_ref": "ACC-1001",
        "recipient_ref": "USR-77",
        "subject": "Following up",
        "body": "Noticed your usage climbed.",
        "intent": "re-engagement",
    },
    "messaging_send_slack_approval": {
        "channel_ref": "revops-approvals",
        "incident_ref": "INC-001",
        "summary": "Draft awaiting approval",
    },
    "analytics_calculate_pipeline_impact": {
        "opportunity_ref": "OPP-2001",
        "signal_type": "stalled_opportunity",
        "days_inactive": 14,
        "usage_growth": "0.4000",
    },
    "audit_write_event": {
        "incident_ref": "INC-001",
        "event_type": "investigation.note",
        "payload": {"note": "probe"},
    },
}


@pytest.fixture
def detected(seeded_session: Session, settings: Settings) -> Session:
    """Seeded, ingested -- so INC-001 exists for the audit tool."""
    from revenue_sentinel.events.pipeline import run_ingestion_cycle

    run_ingestion_cycle(
        seeded_session, evaluated_at=settings.evaluation_timestamp, settings=settings
    )
    return seeded_session


def make_context(
    session: Session,
    settings: Settings,
    *,
    policy: object | None = None,
    behaviour: SimulatedBehaviour | None = None,
    run_id: object | None = None,
) -> ToolContext:
    return ToolContext(
        session=session,
        adapters=build_simulated_adapters(session, behaviour or SimulatedBehaviour()),
        occurred_at=settings.evaluation_timestamp,
        node_name="probe",
        run_id=run_id,  # type: ignore[arg-type]
        policy=policy,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# All 15 tools, happy path
# ---------------------------------------------------------------------------
def test_every_registered_tool_has_a_happy_path_case() -> None:
    """Guard against a tool being added and quietly going untested."""
    assert set(HAPPY_ARGS) == set(REGISTRY)


@pytest.mark.parametrize("spec", TOOL_SPECS, ids=lambda s: s.name)
def test_every_tool_succeeds_on_valid_arguments(
    spec: Any, detected: Session, settings: Settings
) -> None:
    context = make_context(detected, settings, policy=StubPolicyEngine())
    result = dispatch(spec.name, HAPPY_ARGS[spec.name], context)

    assert result["ok"] is True, result
    assert isinstance(result["data"], dict)


@pytest.mark.parametrize("spec", TOOL_SPECS, ids=lambda s: s.name)
def test_every_tool_stamps_the_simulated_status(
    spec: Any, detected: Session, settings: Settings
) -> None:
    """Read from the adapter module, not hardcoded in the envelope (ADR-0004)."""
    context = make_context(detected, settings, policy=StubPolicyEngine())
    result = dispatch(spec.name, HAPPY_ARGS[spec.name], context)

    assert result["integration_status"] == "SIMULATED"


@pytest.mark.parametrize("spec", TOOL_SPECS, ids=lambda s: s.name)
def test_every_tool_rejects_an_unknown_argument(
    spec: Any, detected: Session, settings: Settings
) -> None:
    """The check the SDK's own decorator would silently pass."""
    context = make_context(detected, settings, policy=StubPolicyEngine())
    poisoned = {**HAPPY_ARGS[spec.name], "definitely_not_a_field": 1}

    result = dispatch(spec.name, poisoned, context)

    assert result["ok"] is False
    assert result["error"]["code"] == ToolErrorCode.INVALID_ARGUMENTS.value


def test_the_impact_tool_returns_the_documented_figures(
    detected: Session, settings: Settings
) -> None:
    context = make_context(detected, settings, policy=StubPolicyEngine())
    result = dispatch(
        "analytics_calculate_pipeline_impact",
        HAPPY_ARGS["analytics_calculate_pipeline_impact"],
        context,
    )

    assert result["data"]["weighted_value"] == "108000.00"
    assert result["data"]["at_risk_value"] == "32130.00"
    assert result["data"]["computed_by"] == "deterministic"


def test_the_draft_tool_creates_but_does_not_send(detected: Session, settings: Settings) -> None:
    context = make_context(detected, settings, policy=StubPolicyEngine())
    result = dispatch(
        "messaging_create_email_draft", HAPPY_ARGS["messaging_create_email_draft"], context
    )

    assert result["data"]["created"] is True
    assert result["data"]["sent"] is False


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("crm_get_account", {"account_ref": "ACC-9999"}),
        ("crm_get_opportunity", {"opportunity_ref": "OPP-9999"}),
        ("support_get_open_issues", {"account_ref": "ACC-9999"}),
        ("enrichment_get_company_profile", {"account_ref": "ACC-9999"}),
    ],
)
def test_a_missing_entity_is_not_found_and_not_retryable(
    tool_name: str, arguments: dict[str, Any], detected: Session, settings: Settings
) -> None:
    """An absent record is negative evidence, not a transient failure."""
    result = dispatch(tool_name, arguments, make_context(detected, settings))

    assert result["error"]["code"] == ToolErrorCode.NOT_FOUND.value
    assert result["error"]["retry"] is False


def test_an_unknown_tool_is_refused_and_lists_what_exists(
    detected: Session, settings: Settings
) -> None:
    result = dispatch("messaging_send_email", {}, make_context(detected, settings))

    assert result["error"]["code"] == ToolErrorCode.NOT_FOUND.value
    assert "crm_get_account" in result["error"]["detail"]["available"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"account_ref": "not-a-ref"},
        {"account_ref": "acc-1001"},
        {},
        {"account_ref": "ACC-1001", "extra": True},
    ],
)
def test_malformed_arguments_are_rejected(
    arguments: dict[str, Any], detected: Session, settings: Settings
) -> None:
    result = dispatch("crm_get_account", arguments, make_context(detected, settings))

    assert result["error"]["code"] == ToolErrorCode.INVALID_ARGUMENTS.value
    assert result["error"]["retry"] is True


# ---------------------------------------------------------------------------
# The write gate
# ---------------------------------------------------------------------------
class SpyCrmAdapter:
    """Records whether it was reached at all."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_task(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("create_task")
        return {"created": True}

    def __getattr__(self, name: str) -> Any:
        def _record(**kwargs: Any) -> dict[str, Any]:
            self.calls.append(name)
            return {}

        return _record


@pytest.mark.parametrize(
    "tool_name",
    [
        "crm_create_task",
        "crm_update_opportunity",
        "messaging_create_email_draft",
        "messaging_send_slack_approval",
    ],
)
def test_a_write_without_a_policy_engine_is_refused(
    tool_name: str, detected: Session, settings: Settings
) -> None:
    """A system that can be configured into unauthorised writes eventually performs one.

    Session 11 changed the *shape* of this refusal, not its force. It used to escape the
    dispatcher as `MissingPolicyEngineError`, which over stdio became a protocol-level
    error with no envelope -- indistinguishable from a crash. It is now a typed
    `POLICY_ENGINE_UNAVAILABLE` result. Still fails closed; now says so.
    """
    context = make_context(detected, settings, policy=None)

    envelope = dispatch(tool_name, HAPPY_ARGS[tool_name], context)

    assert envelope["ok"] is False
    error = envelope["error"]
    assert error["code"] == ToolErrorCode.POLICY_ENGINE_UNAVAILABLE.value
    assert error["code"] != ToolErrorCode.POLICY_DENIED.value
    assert error["retry"] is False
    assert error["alternative_route"] is False
    assert "cannot execute without a decision" in error["message"]


def test_a_denied_write_never_reaches_its_adapter(detected: Session, settings: Settings) -> None:
    """Proven with a spy, not inferred from the returned error."""
    spy = SpyCrmAdapter()
    base = make_context(detected, settings, policy=DenyAllPolicyEngine())
    context = ToolContext(
        session=base.session,
        adapters=type(base.adapters)(
            crm=spy,  # type: ignore[arg-type]
            product=base.adapters.product,
            engagement=base.adapters.engagement,
            support=base.adapters.support,
            enrichment=base.adapters.enrichment,
            messaging=base.adapters.messaging,
        ),
        occurred_at=base.occurred_at,
        node_name="probe",
        policy=DenyAllPolicyEngine(),
    )

    result = dispatch("crm_create_task", HAPPY_ARGS["crm_create_task"], context)

    assert result["error"]["code"] == ToolErrorCode.POLICY_DENIED.value
    assert spy.calls == []


def test_policy_denied_forbids_retry_and_rerouting(detected: Session, settings: Settings) -> None:
    context = make_context(detected, settings, policy=DenyAllPolicyEngine())
    result = dispatch("crm_create_task", HAPPY_ARGS["crm_create_task"], context)

    assert result["error"]["retry"] is False
    assert result["error"]["alternative_route"] is False
    assert "different tool" in result["error"]["guidance"]


def test_reads_do_not_require_a_policy_engine(detected: Session, settings: Settings) -> None:
    """Tier 0 has nothing to authorise; routing reads through the gate would make it
    look load-bearing where it is not."""
    result = dispatch(
        "crm_get_account", {"account_ref": "ACC-1001"}, make_context(detected, settings)
    )

    assert result["ok"] is True


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------
@pytest.fixture
def run_id(detected: Session, settings: Settings) -> Any:
    """A real workflow run.

    `tool_calls.run_id` is a foreign key, so a ledger row cannot exist without a run
    to attribute it to -- which is the point of the constraint, and why these tests
    create one rather than inventing an id.
    """
    from revenue_sentinel.core.ids import new_id
    from revenue_sentinel.db.models import workflow as workflow_orm
    from revenue_sentinel.domain.enums import WorkflowStatus

    incident = detected.scalar(
        sa.select(workflow_orm.Incident).where(workflow_orm.Incident.incident_ref == "INC-001")
    )
    assert incident is not None
    run = workflow_orm.WorkflowRun(
        id=new_id(),
        incident_id=incident.id,
        graph_version="test/v1",
        status=WorkflowStatus.RUNNING,
        started_at=settings.evaluation_timestamp,
    )
    detected.add(run)
    detected.flush()
    return run.id


def _tool_calls(session: Session) -> list[obs_orm.ToolCall]:
    return list(
        session.scalars(sa.select(obs_orm.ToolCall).order_by(obs_orm.ToolCall.tool_name)).all()
    )


def test_a_successful_call_is_recorded(detected: Session, settings: Settings, run_id: Any) -> None:
    context = make_context(detected, settings, run_id=run_id)
    dispatch("crm_get_account", {"account_ref": "ACC-1001"}, context)

    rows = _tool_calls(detected)
    assert len(rows) == 1
    assert rows[0].status is ToolCallStatus.SUCCESS
    assert rows[0].tool_name == "crm_get_account"
    assert rows[0].args == {"account_ref": "ACC-1001"}
    assert len(rows[0].result_digest) == 64


def test_an_error_is_recorded_too(detected: Session, settings: Settings, run_id: Any) -> None:
    context = make_context(detected, settings, run_id=run_id)
    dispatch("crm_get_account", {"account_ref": "ACC-9999"}, context)

    rows = _tool_calls(detected)
    assert len(rows) == 1
    assert rows[0].status is ToolCallStatus.ERROR


def test_a_denial_is_recorded(detected: Session, settings: Settings, run_id: Any) -> None:
    """The most interesting kind to have a record of, and the easiest to forget."""
    context = make_context(detected, settings, policy=DenyAllPolicyEngine(), run_id=run_id)
    dispatch("crm_create_task", HAPPY_ARGS["crm_create_task"], context)

    rows = _tool_calls(detected)
    assert len(rows) == 1
    assert rows[0].status is ToolCallStatus.DENIED


def test_calls_in_one_run_share_a_trace_and_differ_by_span(
    detected: Session, settings: Settings, run_id: Any
) -> None:
    counter = CallCounter()
    context = make_context(detected, settings, run_id=run_id)
    dispatch("crm_get_account", {"account_ref": "ACC-1001"}, context, counter=counter)
    dispatch("support_get_open_issues", {"account_ref": "ACC-1001"}, context, counter=counter)

    rows = _tool_calls(detected)
    assert len({row.trace_id for row in rows}) == 1
    assert len({row.span_id for row in rows}) == 2
    assert len({row.parent_span_id for row in rows}) == 1


def test_nothing_is_recorded_without_a_run(detected: Session, settings: Settings) -> None:
    """A tool call outside a run has no run to attribute to; the FK requires one."""
    dispatch("crm_get_account", {"account_ref": "ACC-1001"}, make_context(detected, settings))

    assert _tool_calls(detected) == []


# ---------------------------------------------------------------------------
# Deterministic injection
# ---------------------------------------------------------------------------
def test_injection_is_inert_by_default() -> None:
    assert SimulatedBehaviour().is_inert is True


def test_a_scripted_failure_surfaces_as_its_error_code(
    detected: Session, settings: Settings
) -> None:
    behaviour = SimulatedBehaviour.from_settings(
        latency_ms=0, failure_script="crm_get_account:1=RATE_LIMITED"
    )
    context = make_context(detected, settings, behaviour=behaviour)

    result = dispatch("crm_get_account", {"account_ref": "ACC-1001"}, context)

    assert result["error"]["code"] == ToolErrorCode.RATE_LIMITED.value
    assert result["error"]["retry"] is True


def test_only_the_scripted_call_fails(detected: Session, settings: Settings) -> None:
    """Deterministic, not sampled: the second call succeeds."""
    behaviour = SimulatedBehaviour.from_settings(
        latency_ms=0, failure_script="crm_get_account:1=ADAPTER_ERROR"
    )
    context = make_context(detected, settings, behaviour=behaviour)

    first = dispatch("crm_get_account", {"account_ref": "ACC-1001"}, context)
    second = dispatch("crm_get_account", {"account_ref": "ACC-1001"}, context)

    assert first["error"]["code"] == ToolErrorCode.ADAPTER_ERROR.value
    assert second["ok"] is True


def test_the_same_script_produces_the_same_outcomes_every_run(
    detected: Session, settings: Settings
) -> None:
    outcomes = []
    for _ in range(2):
        behaviour = SimulatedBehaviour.from_settings(
            latency_ms=0, failure_script="crm_get_account:2=ADAPTER_ERROR"
        )
        context = make_context(detected, settings, behaviour=behaviour)
        outcomes.append(
            [
                dispatch("crm_get_account", {"account_ref": "ACC-1001"}, context)["ok"]
                for _ in range(3)
            ]
        )

    assert outcomes[0] == outcomes[1] == [True, False, True]


@pytest.mark.parametrize("script", ["crm_get_account", "crm_get_account:x=BOOM", "a:1="])
def test_a_malformed_failure_script_is_rejected(script: str) -> None:
    with pytest.raises(ValueError, match="malformed failure script"):
        parse_failure_script(script)
