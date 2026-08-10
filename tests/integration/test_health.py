"""`GET /health` -- the only endpoint in Session 1.

Includes the unhappy path. A health endpoint that has only ever been observed
returning 200 is a health endpoint whose failure behaviour is unknown.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from revenue_sentinel.api.main import create_app
from revenue_sentinel.core.config import Settings


@pytest.fixture
def client(engine: Engine, settings: Settings) -> Iterator[TestClient]:
    """A client bound to the isolated test database rather than the dev one."""
    app = create_app(settings=settings, engine=engine)
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_ok_when_the_database_answers(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "reachable"


def test_health_reports_configuration_the_operator_needs(
    client: TestClient, settings: Settings
) -> None:
    body = client.get("/health").json()

    assert body["version"] == "0.1.0"
    assert body["demo_mode"] == settings.demo_mode
    assert body["app_env"] == settings.app_env


def test_health_payload_has_no_unexpected_fields(client: TestClient) -> None:
    """The response model is `extra="forbid"`; keep the wire shape pinned too."""
    assert set(client.get("/health").json()) == {
        "status",
        "version",
        "app_env",
        "demo_mode",
        "database",
    }


def test_health_returns_503_when_the_database_is_unreachable(settings: Settings) -> None:
    """Point the app at a database that does not exist and require it to say so.

    Reported through the status code, not only the body, so an orchestrator can act
    on it without parsing JSON.

    The broken URL is derived by *replacing the database component*, not by string-
    substituting the name `revenue_sentinel`. The substitution version passed only when the
    configured URL happened to contain that name: pointed at any other database it was a
    no-op, the engine stayed healthy, and the test asserted 503 against a working
    connection. Found by running the suite from a fresh checkout against a throwaway
    database, where it returned 200.
    """
    broken = sa.create_engine(
        sa.engine.make_url(settings.database_url).set(database="definitely_not_a_database")
    )
    app = create_app(settings=settings, engine=broken)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"


def test_the_application_exposes_exactly_the_expected_routes(client: TestClient) -> None:
    """The route surface is pinned, so scope creep shows up as a failing test.

    This asserted `{"/health"}` through Session 1, gained three endpoints in Session 2,
    and gained the dashboard read surface in Session 9 -- the requirement moved each
    time, not the assertion. It is still an exact set, so an endpoint added without
    thought fails here.

    **Every addition is a GET.** No mutation endpoint ships, which is the point of
    ADR-0022 and is asserted separately in `test_api_dashboard.py`.
    """
    paths = set(client.app.openapi()["paths"])  # type: ignore[attr-defined]

    assert paths == {
        "/health",
        "/ingest",
        "/incidents",
        "/incidents/{incident_ref}",
        # Session 9 -- dashboard reads
        "/overview",
        "/incidents/{incident_ref}/investigation",
        "/incidents/{incident_ref}/interventions",
        "/incidents/{incident_ref}/timeline",
        "/incidents/{incident_ref}/cost",
        "/incidents/{incident_ref}/uncertain-actions",
        "/approvals",
        "/evaluation/latest",
        # Session 10 -- cost centre, evaluation history, integration catalogue
        "/cost",
        "/evaluation/runs",
        "/integrations",
    }
