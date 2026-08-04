"""Raw event ingestion.

Append-only, and replay-safe **because of a database constraint**:
`UNIQUE (source_system, source_event_id)` on `raw_events`. Re-running ingestion
issues the same inserts and PostgreSQL discards the duplicates, so the guarantee
holds under concurrency as well as under a second `make ingest`.

`ON CONFLICT DO NOTHING` rather than a read-then-write check: the read-then-write
version has a race window between the check and the insert, and it would pass every
single-threaded test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from revenue_sentinel.core.ids import new_id
from revenue_sentinel.db.models import events as orm
from revenue_sentinel.events.sources import SourceEvent


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What one ingestion pass did."""

    batch_id: UUID
    offered: int
    inserted: int

    @property
    def duplicates(self) -> int:
        """Events already present. On a replay this equals `offered`."""
        return self.offered - self.inserted


def ingest_source_events(
    session: Session, events: tuple[SourceEvent, ...], *, received_at: datetime
) -> IngestResult:
    """Write source events to `raw_events`, skipping any already stored.

    `received_at` is injected rather than read from the clock, so a replay produces
    identical rows rather than rows that differ only in when they were replayed.
    """
    batch_id = new_id()
    if not events:
        return IngestResult(batch_id=batch_id, offered=0, inserted=0)

    rows = [
        {
            "id": new_id(),
            "source_system": event.source_system,
            "source_event_id": event.source_event_id,
            "received_at": received_at,
            "payload": {
                "event_type": event.event_type.value,
                "occurred_at": event.occurred_at.isoformat(),
                "data": event.payload,
            },
            "ingest_batch_id": batch_id,
        }
        for event in events
    ]

    statement = (
        insert(orm.RawEvent)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["source_system", "source_event_id"])
        .returning(orm.RawEvent.id)
    )
    inserted = len(session.execute(statement).scalars().all())
    session.flush()

    return IngestResult(batch_id=batch_id, offered=len(rows), inserted=inserted)
