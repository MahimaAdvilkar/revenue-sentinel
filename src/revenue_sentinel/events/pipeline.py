"""The ingestion cycle -- the one entry point the CLI and the API both call.

    sources (SIMULATED) -> raw_events -> normalized_events -> detectors
                                                                  |
                                                      signals -> incidents

Replay safety holds at three independent levels, each enforced by the database
rather than by this function:

| Level | Mechanism |
|---|---|
| Raw event | `UNIQUE (source_system, source_event_id)` |
| Signal | `UNIQUE (dedupe_key)` |
| Incident | `UNIQUE (signal_id)` |

Running the cycle twice over unchanged data therefore produces zero new rows at
every level -- and the third level holds even if the first two were somehow
bypassed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.core.logging import get_logger
from revenue_sentinel.events.dispatcher import run_detectors
from revenue_sentinel.events.ingest import ingest_source_events
from revenue_sentinel.events.normalize import normalize_pending
from revenue_sentinel.events.sources import INGESTION_STATUS, read_source_events
from revenue_sentinel.incidents.service import open_incident_for_signal

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    """What one full cycle did, at every stage."""

    ingestion_status: str
    evaluated_at: datetime
    raw_offered: int
    raw_inserted: int
    normalized: int
    contexts_evaluated: int
    signals_created: int
    signals_deduplicated: int
    incidents_opened: int
    incident_refs: tuple[str, ...]


def run_ingestion_cycle(
    session: Session, *, evaluated_at: datetime, settings: Settings
) -> IngestionSummary:
    """Ingest, normalize, detect, and open incidents.

    `evaluated_at` is injected all the way down: it becomes `received_at` on raw
    events, the detection instant, and the incident's `opened_at`. One clock value
    per cycle, passed rather than read.
    """
    source_events = read_source_events(session)
    ingested = ingest_source_events(session, source_events, received_at=evaluated_at)
    normalized = normalize_pending(session)
    detection, new_signals = run_detectors(session, evaluated_at=evaluated_at, settings=settings)

    incident_refs: list[str] = []
    for signal in new_signals:
        incident = open_incident_for_signal(session, signal, occurred_at=evaluated_at)
        incident_refs.append(incident.incident_ref)

    summary = IngestionSummary(
        ingestion_status=INGESTION_STATUS,
        evaluated_at=evaluated_at,
        raw_offered=ingested.offered,
        raw_inserted=ingested.inserted,
        normalized=normalized.normalized,
        contexts_evaluated=detection.contexts_evaluated,
        signals_created=detection.signals_created,
        signals_deduplicated=detection.deduplicated,
        incidents_opened=len(incident_refs),
        incident_refs=tuple(incident_refs),
    )

    logger.info(
        "ingestion_cycle_complete",
        ingestion_status=summary.ingestion_status,
        raw_inserted=summary.raw_inserted,
        normalized=summary.normalized,
        signals_created=summary.signals_created,
        incidents_opened=summary.incidents_opened,
    )
    return summary
