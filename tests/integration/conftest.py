"""Fixtures shared by the integration suite.

`detected` and `investigated` began life inside `test_investigation.py`. They moved
here in Session 5 because `test_governance.py` asserts against the *same* golden run --
and two modules each running their own investigation would be two runs that could
disagree, which is precisely the kind of divergence the golden scenario exists to rule
out.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from revenue_sentinel.api.main import create_app
from revenue_sentinel.core.config import Settings
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.seeding import seed_database
from revenue_sentinel.events.pipeline import run_ingestion_cycle
from revenue_sentinel.governance import approvals
from revenue_sentinel.orchestration import runner
from revenue_sentinel.orchestration.runner import run_investigation


@pytest.fixture
def detected(
    seeded_session: Session, settings: Settings, evaluation_timestamp: datetime
) -> Session:
    """A seeded database with INC-001 open and triaged."""
    run_ingestion_cycle(seeded_session, evaluated_at=evaluation_timestamp, settings=settings)
    return seeded_session


@pytest.fixture
def investigated(detected: Session, settings: Settings) -> runner.InvestigationOutcome:
    """One complete offline investigation of INC-001, through the MCP-backed graph."""
    return run_investigation(detected, "INC-001", settings=settings)


# ---------------------------------------------------------------------------
# API fixtures (Session 9-10)
# ---------------------------------------------------------------------------
INCIDENT = "INC-001"


@pytest.fixture
def dashboard(engine: Engine, settings: Settings) -> Iterator[TestClient]:
    """A client over a database holding a **committed** golden run.

    The app opens its own sessions, so it cannot see the rolled-back transaction the
    other integration tests use -- the same reason `test_api_incidents.py` commits. This
    fixture runs the full flow (ingest, investigate, approve, resume) and cleans up
    afterwards.
    """
    # Truncate on the way in as well as out. Cleaning up only on teardown leaves a failed
    # run's committed rows behind for the next test, which then fails for a reason that
    # has nothing to do with it.
    _cleanup(engine)
    with Session(engine) as setup:
        seed_database(setup, seed=settings.seed, evaluated_at=settings.evaluation_timestamp)
        run_ingestion_cycle(setup, evaluated_at=settings.evaluation_timestamp, settings=settings)
        outcome = runner.run_investigation(setup, INCIDENT, settings=settings)
        request = setup.scalar(
            sa.select(gov_orm.ApprovalRequest).where(
                gov_orm.ApprovalRequest.run_id == outcome.run_id
            )
        )
        assert request is not None
        approvals.decide(
            setup,
            request,
            approved=True,
            decided_by="usr:revenue-lead",
            occurred_at=settings.evaluation_timestamp,
        )
        runner.resume_investigation(setup, INCIDENT, settings=settings)
        setup.commit()

    app = create_app(settings=settings, engine=engine)
    with TestClient(app) as client:
        yield client

    _cleanup(engine)


@pytest.fixture
def client(dashboard: TestClient) -> TestClient:
    """Alias, so schema-level tests read naturally."""
    return dashboard


def _reset(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(sa.text("ALTER SEQUENCE incident_ref_seq RESTART WITH 1"))
        connection.execute(sa.text("ALTER SEQUENCE approval_ref_seq RESTART WITH 1"))


def _cleanup(engine: Engine) -> None:
    """Truncate everything these fixtures commit.

    `budgets` belongs on this list even though the golden run never writes one: the
    dashboard tests configure a budget to assert microdollar precision, and a leaked row
    is not inert. It made three unrelated tests fail -- one asserting that an unbudgeted
    system is not blocked, and the 0007 downgrade guard, which correctly refused to
    discard sub-cent spend. A committed row that survives its test is a shared fixture
    nobody declared.
    """
    tables = (
        "evaluation_results, evaluation_runs, action_records, approval_requests, "
        "policy_evaluations, interventions, impact_assessments, hypothesis_evidence, "
        "hypotheses, evidence_items, agent_decisions, model_calls, tool_calls, "
        "cost_entries, budgets, workflow_transitions, workflow_runs, audit_events, "
        "incidents, signals, normalized_events, raw_events, activities, usage_snapshots, "
        "engagement_events, support_issues, company_profiles, opportunities, accounts"
    )
    with engine.begin() as connection:
        connection.execute(sa.text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    _reset(engine)
