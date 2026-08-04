"""`POST /ingest` -- run one ingestion cycle.

Thin: parse, delegate to `events/pipeline.py`, serialize (boundary R2). All the
logic lives in the pipeline, which is importable and tested without an HTTP server.

The endpoint is not idempotent in the "same response every time" sense -- the first
call opens incidents and the second reports zero -- but it **is** replay-safe: the
second call creates no duplicate rows at any of the three boundaries. That
distinction is the point of the whole design, so the response reports both what was
created and what was deduplicated.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from revenue_sentinel.api.deps import get_session, get_settings_from_app
from revenue_sentinel.api.schemas import IngestResponse
from revenue_sentinel.core.config import Settings
from revenue_sentinel.events.pipeline import run_ingestion_cycle

router = APIRouter(tags=["ingestion"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Run one ingestion cycle over the SIMULATED source feed",
)
def post_ingest(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> IngestResponse:
    """Ingest, normalize, detect, and open incidents.

    The evaluation instant is taken from configuration, never from the clock, so
    two calls in the same deployment evaluate against the same reference time and
    the demo stays reproducible.
    """
    summary = run_ingestion_cycle(
        session, evaluated_at=settings.evaluation_timestamp, settings=settings
    )
    return IngestResponse(
        ingestion_status=summary.ingestion_status,
        evaluated_at=summary.evaluated_at,
        raw_events_offered=summary.raw_offered,
        raw_events_inserted=summary.raw_inserted,
        events_normalized=summary.normalized,
        opportunities_evaluated=summary.contexts_evaluated,
        signals_created=summary.signals_created,
        signals_deduplicated=summary.signals_deduplicated,
        incidents_opened=summary.incidents_opened,
        incident_refs=summary.incident_refs,
    )
