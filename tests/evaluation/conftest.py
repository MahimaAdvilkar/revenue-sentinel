"""Fixtures shared by the integration suite.

`detected` and `investigated` began life inside `test_investigation.py`. They moved
here in Session 5 because `test_governance.py` asserts against the *same* golden run --
and two modules each running their own investigation would be two runs that could
disagree, which is precisely the kind of divergence the golden scenario exists to rule
out.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.events.pipeline import run_ingestion_cycle
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
