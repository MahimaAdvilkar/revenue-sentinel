"""`POST /ingest`, `GET /incidents`, `GET /incidents/{incident_ref}`.

Acceptance criterion 8: after `make ingest`, `INC-001` is visible over HTTP with the
signal that produced it.

These run against the isolated test database with a real transaction per request,
so they exercise the dependency wiring rather than calling the pipeline directly.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from revenue_sentinel.api.main import create_app
from revenue_sentinel.core.config import Settings
from revenue_sentinel.db.models import events as event_orm
from revenue_sentinel.db.models import gtm as gtm_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.db.seeding import seed_database


@pytest.fixture
def api(engine: Engine, settings: Settings) -> Iterator[TestClient]:
    """A client over the test database, seeded and cleared around each test.

    The app opens its own sessions, so it cannot participate in the rolled-back
    transaction the other integration tests use. This fixture therefore commits and
    cleans up explicitly.
    """
    with Session(engine) as setup:
        setup.execute(sa.text("ALTER SEQUENCE incident_ref_seq RESTART WITH 1"))
        seed_database(setup, seed=settings.seed, evaluated_at=settings.evaluation_timestamp)
        setup.commit()

    app = create_app(settings=settings, engine=engine)
    with TestClient(app) as client:
        yield client

    with Session(engine) as teardown:
        for model in (
            workflow_orm.Incident,
            event_orm.Signal,
            event_orm.NormalizedEvent,
            event_orm.RawEvent,
            gtm_orm.Activity,
            gtm_orm.UsageSnapshot,
            gtm_orm.EngagementEvent,
            gtm_orm.SupportIssue,
            gtm_orm.CompanyProfile,
            gtm_orm.Opportunity,
            gtm_orm.Account,
        ):
            teardown.execute(sa.delete(model))
        teardown.execute(sa.text("DELETE FROM audit_events"))
        teardown.commit()


# ---------------------------------------------------------------------------
# POST /ingest
# ---------------------------------------------------------------------------
def test_ingest_runs_a_cycle_and_reports_what_it_did(api: TestClient) -> None:
    response = api.post("/ingest")

    assert response.status_code == 200
    body = response.json()
    assert body["raw_events_inserted"] == 72
    assert body["events_normalized"] == 72
    assert body["opportunities_evaluated"] == 15
    assert body["signals_created"] == 1
    assert body["incidents_opened"] == 1
    assert body["incident_refs"] == ["INC-001"]


def test_ingest_always_declares_the_feed_is_simulated(api: TestClient) -> None:
    """Rule 5 -- a caller cannot mistake this for a real source feed."""
    assert api.post("/ingest").json()["ingestion_status"] == "SIMULATED"


def test_ingest_uses_the_injected_evaluation_instant(api: TestClient, settings: Settings) -> None:
    body = api.post("/ingest").json()
    assert body["evaluated_at"].startswith(
        settings.evaluation_timestamp.isoformat().replace("+00:00", "")
    )


def test_a_second_ingest_creates_nothing(api: TestClient) -> None:
    api.post("/ingest")
    body = api.post("/ingest").json()

    assert body["raw_events_inserted"] == 0
    assert body["signals_created"] == 0
    assert body["signals_deduplicated"] == 1
    assert body["incidents_opened"] == 0
    assert body["incident_refs"] == []


# ---------------------------------------------------------------------------
# GET /incidents
# ---------------------------------------------------------------------------
def test_the_queue_is_empty_before_ingestion(api: TestClient) -> None:
    body = api.get("/incidents").json()
    assert body["count"] == 0
    assert body["incidents"] == []


def test_the_queue_lists_the_opened_incident(api: TestClient) -> None:
    api.post("/ingest")
    body = api.get("/incidents").json()

    assert body["count"] == 1
    incident = body["incidents"][0]
    assert incident["incident_ref"] == "INC-001"
    assert incident["severity"] == "high"
    assert incident["status"] == "triaged"
    assert incident["account_ref"] == "ACC-1001"
    assert incident["opportunity_ref"] == "OPP-2001"


@pytest.mark.parametrize(
    ("query", "expected"),
    [("status=triaged", 1), ("status=completed", 0), ("severity=high", 1), ("severity=low", 0)],
)
def test_the_queue_filters(api: TestClient, query: str, expected: int) -> None:
    api.post("/ingest")
    assert api.get(f"/incidents?{query}").json()["count"] == expected


def test_an_unknown_filter_value_is_rejected(api: TestClient) -> None:
    assert api.get("/incidents?status=not-a-status").status_code == 422


def test_the_limit_is_bounded(api: TestClient) -> None:
    assert api.get("/incidents?limit=0").status_code == 422
    assert api.get("/incidents?limit=500").status_code == 422


# ---------------------------------------------------------------------------
# GET /incidents/{incident_ref}
# ---------------------------------------------------------------------------
def test_incident_detail_includes_the_signal_that_produced_it(api: TestClient) -> None:
    """Acceptance criterion 8."""
    api.post("/ingest")
    body = api.get("/incidents/INC-001").json()

    assert body["incident_ref"] == "INC-001"
    assert body["title"] == "Northwind Logistics - Platform Expansion stalled at proposal"

    signal = body["signal"]
    assert signal["signal_type"] == "stalled_opportunity"
    assert signal["detector_version"] == "stalled_opportunity/v1"
    assert signal["severity"] == "high"
    assert len(signal["dedupe_key"]) == 64
    assert signal["evidence_event_count"] > 0


def test_incident_detail_includes_the_account_and_opportunity(api: TestClient) -> None:
    api.post("/ingest")
    body = api.get("/incidents/INC-001").json()

    assert body["account"]["account_ref"] == "ACC-1001"
    assert body["account"]["name"] == "Northwind Logistics"
    assert body["opportunity"]["opportunity_ref"] == "OPP-2001"
    assert body["opportunity"]["amount"] == "180000.00"
    assert body["opportunity"]["stage"] == "proposal"


def test_every_gtm_record_on_the_wire_is_marked_simulated(api: TestClient) -> None:
    """The dashboard renders its SIMULATED badge from the payload, not a constant."""
    api.post("/ingest")
    body = api.get("/incidents/INC-001").json()

    assert body["account"]["is_simulated"] is True
    assert body["opportunity"]["is_simulated"] is True


def test_an_unknown_incident_returns_404(api: TestClient) -> None:
    response = api.get("/incidents/INC-999")

    assert response.status_code == 404
    assert "INC-999" in response.json()["detail"]


def test_the_route_surface_is_exactly_the_four_documented_endpoints(
    api: TestClient,
) -> None:
    paths = set(api.app.openapi()["paths"])  # type: ignore[attr-defined]
    assert paths == {"/health", "/ingest", "/incidents", "/incidents/{incident_ref}"}
