"""The dashboard read surface: contract, precision, and what it refuses to do.

Three properties beyond "it returns 200":

* **Read-only.** No mutation endpoint exists. Asserted against the OpenAPI schema rather
  than by remembering not to add one (ADR-0022).
* **Full precision.** Money and cost are strings, so `$0.000000` survives JSON. A float
  would render real sub-cent spend as `0.0`.
* **SIMULATED is data-driven**, so it cannot drift from what actually happened.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

INCIDENT = "INC-001"


# ---------------------------------------------------------------------------
# Read-only, by construction
# ---------------------------------------------------------------------------
def test_the_dashboard_exposes_no_mutation_endpoint(client: TestClient) -> None:
    """ADR-0022. An approve button with no authentication behind it would imply a
    session and an accountable user that do not exist."""
    schema = client.get("/openapi.json").json()

    mutating = [
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        for method in operations
        if method in {"post", "put", "patch", "delete"} and not path.startswith("/ingest")
    ]
    assert mutating == [], f"unexpected mutation endpoints: {mutating}"


def test_the_approval_inbox_renders_the_command_rather_than_running_it(
    dashboard: TestClient,
) -> None:
    body = dashboard.get("/approvals").json()

    # The fixture carries the run through approval, so the inbox is legitimately empty.
    # What must hold regardless is that the endpoint never offers a way to *decide* --
    # only a command to run, and the note explaining why (ADR-0022).
    assert body["pending"] == []
    assert "CLAIMED identity" in body["identity_note"]
    assert "no authentication" in body["identity_note"]
    assert "CLI only" in body["identity_note"]


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------
def test_the_overview_reports_dollars_at_risk(dashboard: TestClient) -> None:
    body = dashboard.get("/overview").json()

    assert body["total_at_risk"] == "32130.00"
    assert body["total_weighted"] == "108000.00"
    # The golden run finishes, so the incident is terminal and nothing is outstanding.
    assert body["open_incidents"] == 0
    assert body["incidents_by_status"]["completed"] == 1
    assert body["integration_status"] == "SIMULATED"


def test_the_investigation_view_carries_evidence_hypotheses_and_impact(
    dashboard: TestClient,
) -> None:
    body = dashboard.get(f"/incidents/{INCIDENT}/investigation").json()

    assert len(body["evidence"]) == 6
    assert len(body["hypotheses"]) == 2
    assert body["impact"]["at_risk_value"] == "32130.00"
    assert body["impact"]["computed_by"] == "deterministic"
    assert all(item["trust_level"] == "untrusted" for item in body["evidence"])
    assert all(item["integration_status"] == "SIMULATED" for item in body["evidence"])


def test_every_hypothesis_view_carries_its_citations(dashboard: TestClient) -> None:
    body = dashboard.get(f"/incidents/{INCIDENT}/investigation").json()

    for hypothesis in body["hypotheses"]:
        assert hypothesis["cites"], "a hypothesis with no citation should be impossible"
        assert all(ref.startswith("EV-") for ref in hypothesis["cites"])


def test_the_interventions_view_shows_the_decision_and_its_rules(
    dashboard: TestClient,
) -> None:
    body = dashboard.get(f"/incidents/{INCIDENT}/interventions").json()

    assert len(body) == 3
    assert [item["rank"] for item in body] == [1, 2, 3]
    assert sorted(item["decision"] for item in body) == [
        "allow",
        "deny",
        "require_approval",
    ]
    for item in body:
        assert item["matched_rules"], "a decision without rules cannot be audited"
        assert item["integration_status"] == "SIMULATED"


def test_the_timeline_preserves_trace_correlation(dashboard: TestClient) -> None:
    body = dashboard.get(f"/incidents/{INCIDENT}/timeline").json()

    assert body["trace_count"] == 1
    sources = {event["source"] for event in body["events"]}
    assert sources == {"model_call", "tool_call", "cost_entry", "audit_event"}


def test_absent_tracing_metadata_is_null_rather_than_invented(
    dashboard: TestClient,
) -> None:
    """`audit_events` carry no trace. `null` is the honest signal."""
    body = dashboard.get(f"/incidents/{INCIDENT}/timeline").json()
    audits = [event for event in body["events"] if event["source"] == "audit_event"]

    assert audits
    assert all(event["trace_id"] is None and event["span_id"] is None for event in audits)


def test_cost_serialises_at_microdollar_precision(dashboard: TestClient) -> None:
    """A float would render `$0.000000` as `0.0` and undo six decimal places."""
    body = dashboard.get(f"/incidents/{INCIDENT}/cost").json()

    assert body["total_cost"] == "0.000000"
    assert body["model_cost"] == "0.000000"
    assert body["tool_cost"] == "0.000000"
    assert isinstance(body["total_cost"], str)
    assert body["pricing_versions"] == ["pricing/2026-08"]
    assert "ADR-0019" in body["concurrency_note"]


def test_the_cost_ledger_labels_model_and_tool_rows(dashboard: TestClient) -> None:
    body = dashboard.get(f"/incidents/{INCIDENT}/cost").json()
    kinds = {entry["kind"] for entry in body["ledger"]}

    assert kinds == {"model", "tool"}
    assert all(entry["amount_usd"] == "0.000000" for entry in body["ledger"])


def test_an_unknown_incident_is_a_clean_404(dashboard: TestClient) -> None:
    response = dashboard.get("/incidents/INC-404/investigation")

    assert response.status_code == 404
    assert "INC-404" in response.json()["detail"]


def test_the_evaluation_view_states_that_no_judge_was_used(
    dashboard: TestClient, engine: Engine
) -> None:
    from revenue_sentinel.core.config import get_settings
    from revenue_sentinel.cost import reporting
    from revenue_sentinel.evaluation.service import evaluate

    with Session(engine) as session:
        evaluate(
            session,
            run_id=reporting.latest_run_id(session, INCIDENT),
            occurred_at=get_settings().evaluation_timestamp,
        )
        session.commit()

    body = dashboard.get("/evaluation/latest").json()
    assert body["llm_judge_used"] is False
    assert body["evaluation_cost"] == "0.000000"
    assert body["total"] == body["passed"]
    assert any(item["check_name"] == "no_llm_arithmetic" for item in body["results"])
