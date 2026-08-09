"""Cost centre, evaluation history, and the integration catalogue.

The interesting assertions are the ones about what these endpoints *decline* to claim:
cache effectiveness reports "never observed" rather than `0%`, the model mix says how
many calls were replayed, and evaluation history is a list that keeps failures rather
than a status that forgets them.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import CostType


def test_the_cost_centre_totals_match_the_ledger(dashboard: TestClient) -> None:
    body = dashboard.get("/cost").json()

    assert body["total_cost"] == "0.000000"
    assert body["model_cost"] == "0.000000"
    assert body["tool_cost"] == "0.000000"
    assert body["model_calls"] == 4
    assert body["tool_calls"] == 7
    assert body["pricing_versions"] == ["pricing/2026-08"]


def test_cache_effectiveness_reports_never_observed_rather_than_zero(
    dashboard: TestClient,
) -> None:
    """The distinction this endpoint exists to preserve.

    No live API call has ever been made, so the cache counters are all zero. Reporting
    `0%` would read as "caching works badly" rather than "caching has never run".
    """
    metric = dashboard.get("/cost").json()["cache_effectiveness"]

    assert metric["observed"] is False
    assert metric["value"] is None
    assert "Never observed" in metric["note"]
    assert "absence of data" in metric["note"]
    assert metric["value"] != "0%"


def test_the_model_mix_declares_how_many_calls_were_replayed(dashboard: TestClient) -> None:
    """A mix that did not say so would look like a routing measurement."""
    mix = dashboard.get("/cost").json()["model_mix"]

    assert mix
    for entry in mix:
        assert entry["replayed"] == entry["calls"], "every v1 call is a fixture replay"
        assert entry["cost_usd"] == "0.000000"


def test_per_incident_cost_splits_model_and_tool(dashboard: TestClient) -> None:
    """Split properly rather than reported with zeroed components -- a column that
    always reads 0.000000 looks like a measurement, not an unfilled field."""
    rows = dashboard.get("/cost").json()["by_incident"]

    assert rows
    row = rows[0]
    assert row["incident_ref"] == "INC-001"
    assert row["model_calls"] == 4
    assert row["tool_calls"] == 7
    assert row["total_cost"] == "0.000000"


def test_per_incident_cost_is_computed_rather_than_a_placeholder(
    dashboard: TestClient, engine: object
) -> None:
    """The golden run costs $0.000000, which makes a real aggregation and a hardcoded
    zero look identical on screen.

    So this puts non-zero money in the ledger and checks the endpoint follows it: model
    and tool land in their own columns, the total is their sum, and the call counts move
    too. A placeholder cannot pass this.
    """
    from revenue_sentinel.core.ids import new_id

    with Session(engine) as session:  # type: ignore[arg-type]
        model_call_id = session.scalar(sa.select(obs_orm.ModelCall.id).limit(1))
        tool_call_id = session.scalar(sa.select(obs_orm.ToolCall.id).limit(1))
        run_id = session.scalar(sa.select(obs_orm.CostEntry.run_id).limit(1))
        assert model_call_id and tool_call_id and run_id

        recorded_at = session.scalar(sa.select(obs_orm.CostEntry.recorded_at).limit(1))
        for source, amount in (
            ({"model_call_id": model_call_id}, Decimal("1.234567")),
            ({"tool_call_id": tool_call_id}, Decimal("0.000500")),
        ):
            session.add(
                obs_orm.CostEntry(
                    id=new_id(),
                    run_id=run_id,
                    cost_type=(
                        CostType.MODEL_INFERENCE
                        if "model_call_id" in source
                        else CostType.TOOL_INVOCATION
                    ),
                    amount_usd=amount,
                    pricing_version="pricing/2026-08",
                    recorded_at=recorded_at,
                    **source,
                )
            )
        session.commit()

    row = dashboard.get("/cost").json()["by_incident"][0]

    assert row["incident_ref"] == "INC-001"
    assert row["model_cost"] == "1.234567"
    assert row["tool_cost"] == "0.000500"
    assert row["total_cost"] == "1.235067"
    assert row["model_calls"] == 5
    assert row["tool_calls"] == 8


def test_by_incident_is_ranked_by_total_spend(dashboard: TestClient) -> None:
    """Ranking is stated behaviour, so it is asserted rather than assumed."""
    rows = dashboard.get("/cost").json()["by_incident"]

    totals = [Decimal(row["total_cost"]) for row in rows]
    assert totals == sorted(totals, reverse=True)
    # Ties fall back to the reference, so the order is total rather than dict order.
    refs = [row["incident_ref"] for row in rows]
    assert refs == [
        ref for _, ref in sorted(zip(totals, refs, strict=True), key=lambda p: (-p[0], p[1]))
    ]


def test_the_cost_centre_is_read_only(dashboard: TestClient) -> None:
    for method in ("post", "put", "patch", "delete"):
        assert getattr(dashboard, method)("/cost").status_code == 405


def test_the_cost_centre_carries_the_concurrency_caveat(dashboard: TestClient) -> None:
    note = dashboard.get("/cost").json()["concurrency_note"]

    assert "not atomic" in note
    assert "ADR-0019" in note


def test_budgets_report_remaining_at_microdollar_precision(
    dashboard: TestClient, engine: object
) -> None:
    from revenue_sentinel.core.ids import new_id
    from revenue_sentinel.domain.enums import BudgetPeriod, BudgetScope

    with Session(engine) as session:  # type: ignore[arg-type]
        session.add(
            obs_orm.Budget(
                id=new_id(),
                scope=BudgetScope.GLOBAL,
                scope_ref=None,
                period=BudgetPeriod.MONTHLY,
                limit_usd=Decimal("25.000000"),
                consumed_usd=Decimal("0.000150"),
                hard_stop=True,
            )
        )
        session.commit()

    budgets = dashboard.get("/cost").json()["budgets"]
    assert budgets
    assert budgets[0]["remaining_usd"] == "24.999850"
    assert budgets[0]["limit_usd"] == "25.000000"


# ---------------------------------------------------------------------------
# Evaluation history
# ---------------------------------------------------------------------------
def test_evaluation_history_is_a_list_not_a_status(dashboard: TestClient, engine: object) -> None:
    """ADR-0021 made attempts append-only so a later pass cannot erase an earlier
    failure. An endpoint returning only the latest would undo that."""
    from revenue_sentinel.core.config import get_settings
    from revenue_sentinel.cost import reporting
    from revenue_sentinel.evaluation.service import evaluate

    with Session(engine) as session:  # type: ignore[arg-type]
        run_id = reporting.latest_run_id(session, "INC-001")
        evaluate(session, run_id=run_id, occurred_at=get_settings().evaluation_timestamp)
        evaluate(session, run_id=run_id, occurred_at=get_settings().evaluation_timestamp)
        session.commit()

    body = dashboard.get("/evaluation/runs").json()

    assert len(body["runs"]) >= 2
    assert body["llm_judge_used"] is False
    assert body["evaluation_cost"] == "0.000000"
    for run in body["runs"]:
        assert run["evaluator_version"] == "evaluator/v1"
        assert run["outcome"] in {"passed", "failed"}


def test_a_failed_attempt_stays_in_the_history(dashboard: TestClient, engine: object) -> None:
    from revenue_sentinel.core.config import get_settings
    from revenue_sentinel.cost import reporting
    from revenue_sentinel.db.models import investigation as inv_orm
    from revenue_sentinel.evaluation.service import evaluate

    with Session(engine) as session:  # type: ignore[arg-type]
        run_id = reporting.latest_run_id(session, "INC-001")
        assessment = session.scalar(
            sa.select(inv_orm.ImpactAssessment).where(inv_orm.ImpactAssessment.run_id == run_id)
        )
        assert assessment is not None
        original = assessment.at_risk_value

        assessment.at_risk_value = Decimal("1.00")
        session.flush()
        evaluate(session, run_id=run_id, occurred_at=get_settings().evaluation_timestamp)

        assessment.at_risk_value = original
        session.flush()
        evaluate(session, run_id=run_id, occurred_at=get_settings().evaluation_timestamp)
        session.commit()

    outcomes = [run["outcome"] for run in dashboard.get("/evaluation/runs").json()["runs"]]
    assert "failed" in outcomes, "the failed attempt was erased by the later pass"
    assert "passed" in outcomes


def test_history_ordering_is_total_and_deterministic(dashboard: TestClient, engine: object) -> None:
    """Every attempt of the golden run shares the frozen EVALUATION_TIMESTAMP.

    Ordering by `started_at` would therefore be arbitrary between them -- the failure
    could appear above or below the later pass, differently per request. `seq` (migration
    0008) is monotonic per insert, so the order is total and the same every time.
    """
    from revenue_sentinel.core.config import get_settings
    from revenue_sentinel.cost import reporting
    from revenue_sentinel.evaluation.service import evaluate

    with Session(engine) as session:  # type: ignore[arg-type]
        run_id = reporting.latest_run_id(session, "INC-001")
        for _ in range(3):
            evaluate(session, run_id=run_id, occurred_at=get_settings().evaluation_timestamp)
        session.commit()

    runs = dashboard.get("/evaluation/runs").json()["runs"]

    assert len({run["started_at"] for run in runs}) == 1, "the tie this ordering must survive"
    sequences = [run["sequence"] for run in runs]
    assert sequences == sorted(sequences, reverse=True)
    assert len(set(sequences)) == len(sequences)
    # Same request, same order -- not merely sorted once.
    assert [
        run["evaluation_run_id"] for run in dashboard.get("/evaluation/runs").json()["runs"]
    ] == [run["evaluation_run_id"] for run in runs]


def test_history_is_never_collapsed_to_a_current_status(
    dashboard: TestClient, engine: object
) -> None:
    """No field on this response says "the" outcome. Every attempt carries its own."""
    from revenue_sentinel.core.config import get_settings
    from revenue_sentinel.cost import reporting
    from revenue_sentinel.evaluation.service import evaluate

    with Session(engine) as session:  # type: ignore[arg-type]
        run_id = reporting.latest_run_id(session, "INC-001")
        evaluate(session, run_id=run_id, occurred_at=get_settings().evaluation_timestamp)
        session.commit()

    body = dashboard.get("/evaluation/runs").json()

    assert set(body) == {"runs", "llm_judge_used", "evaluation_cost"}
    assert all("outcome" in run for run in body["runs"])


def test_evaluation_history_is_read_only(dashboard: TestClient) -> None:
    for method in ("post", "put", "patch", "delete"):
        assert getattr(dashboard, method)("/evaluation/runs").status_code == 405


# ---------------------------------------------------------------------------
# Integration catalogue
# ---------------------------------------------------------------------------
def test_the_catalogue_reads_status_from_the_adapters_themselves(
    dashboard: TestClient,
) -> None:
    """The same constant stamped onto every tool result. A catalogue that could
    disagree with the tool results would be worse than no catalogue."""
    body = dashboard.get("/integrations").json()

    assert len(body["integrations"]) == 6
    assert all(item["integration_status"] == "SIMULATED" for item in body["integrations"])
    assert body["any_real"] is False


def test_the_catalogue_names_every_port_and_adapter_module(dashboard: TestClient) -> None:
    body = dashboard.get("/integrations").json()

    for item in body["integrations"]:
        assert item["module"].startswith("integrations/simulated/")
        assert item["port"].startswith("integrations/ports/")


def test_when_real_copy_is_the_adapters_own_words(dashboard: TestClient) -> None:
    """Not UI copy. Each note is a headed paragraph lifted from the adapter docstring,
    so the roadmap on the screen cannot drift from the roadmap in the code."""
    from revenue_sentinel.integrations.simulated import crm

    body = dashboard.get("/integrations").json()
    entry = next(item for item in body["integrations"] if item["name"] == "CRM")

    assert entry["when_real_documented"] is True
    assert [note["heading"] for note in entry["when_real"]][:2] == ["API", "Auth"]

    adapter_doc = " ".join((crm.__doc__ or "").split())
    for note in entry["when_real"]:
        assert note["body"] in adapter_doc, f"{note['heading']} was not written by the adapter"


def test_every_adapter_documents_what_changes_when_real(dashboard: TestClient) -> None:
    body = dashboard.get("/integrations").json()

    for item in body["integrations"]:
        assert item["when_real_documented"] is True, item["module"]
        assert len(item["when_real"]) >= 4
        assert item["summary"].endswith("SIMULATED.")


def test_the_catalogue_is_read_only(dashboard: TestClient) -> None:
    """Rule 7/8 and ADR-0022: nothing here mutates, including the status."""
    for method in ("post", "put", "patch", "delete"):
        response = getattr(dashboard, method)("/integrations")
        assert response.status_code == 405


def test_any_real_is_computed_rather_than_hardcoded(dashboard: TestClient) -> None:
    """`any_real` stops being false the moment a real adapter is bound."""
    body = dashboard.get("/integrations").json()
    statuses = {item["integration_status"] for item in body["integrations"]}

    assert body["any_real"] == any(status != "SIMULATED" for status in statuses)


def test_any_real_follows_the_adapter_when_one_stops_being_simulated(
    dashboard: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assertion that matters most, because it is the one nobody can test in v1
    by waiting: move the adapter's own constant and watch the API follow."""
    from revenue_sentinel.integrations.simulated import crm

    monkeypatch.setattr(crm, "INTEGRATION_STATUS", "IMPLEMENTED")

    body = dashboard.get("/integrations").json()
    entry = next(item for item in body["integrations"] if item["name"] == "CRM")

    assert entry["integration_status"] == "IMPLEMENTED"
    assert body["any_real"] is True
