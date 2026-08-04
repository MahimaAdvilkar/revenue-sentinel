"""Detector dispatch.

Builds a `DetectionContext` per opportunity, runs every **implemented** detector
against it, and persists the candidates that come back.

The dispatcher does all the I/O so the detectors can do none. It is the only place
in the detection path that touches a session, which is what makes "detectors are
pure" a structural fact rather than a coding convention.

Signal persistence is replay-safe by constraint: `signals.dedupe_key` is UNIQUE and
inserts use `ON CONFLICT DO NOTHING`, so a second cycle over unchanged data creates
no second signal and therefore no second incident.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.core.ids import deterministic_uuid
from revenue_sentinel.db.models import events as event_orm
from revenue_sentinel.db.models import gtm as gtm_orm
from revenue_sentinel.domain.enums import SALES_TOUCH_TYPES
from revenue_sentinel.domain.events import EventEnvelope
from revenue_sentinel.domain.gtm import Account, Opportunity, UsageSnapshot
from revenue_sentinel.domain.signals import SignalCandidate
from revenue_sentinel.signals.protocol import DetectionContext
from revenue_sentinel.signals.registry import implemented_detectors


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """What one detection pass did."""

    contexts_evaluated: int
    candidates: int
    signals_created: int

    @property
    def deduplicated(self) -> int:
        """Candidates the database refused as duplicates of an existing signal."""
        return self.candidates - self.signals_created


def build_detection_context(
    session: Session, opportunity_row: gtm_orm.Opportunity, *, evaluated_at: datetime
) -> DetectionContext | None:
    """Assemble everything a detector may look at for one opportunity."""
    account_row = session.get(gtm_orm.Account, opportunity_row.account_id)
    if account_row is None:
        return None

    latest_sales_touch = session.scalar(
        sa.select(sa.func.max(gtm_orm.Activity.occurred_at)).where(
            gtm_orm.Activity.opportunity_id == opportunity_row.id,
            gtm_orm.Activity.activity_type.in_(list(SALES_TOUCH_TYPES)),
        )
    )

    usage_rows = session.scalars(
        sa.select(gtm_orm.UsageSnapshot)
        .where(gtm_orm.UsageSnapshot.account_id == account_row.id)
        .order_by(gtm_orm.UsageSnapshot.period_start)
    ).all()

    event_rows = session.scalars(
        sa.select(event_orm.NormalizedEvent)
        .where(
            sa.or_(
                event_orm.NormalizedEvent.opportunity_ref == opportunity_row.opportunity_ref,
                event_orm.NormalizedEvent.account_ref == account_row.account_ref,
            )
        )
        .order_by(event_orm.NormalizedEvent.occurred_at)
    ).all()

    return DetectionContext(
        evaluated_at=evaluated_at,
        account=Account.model_validate(account_row),
        opportunity=Opportunity.model_validate(opportunity_row),
        latest_sales_touch=latest_sales_touch,
        usage_window=tuple(UsageSnapshot.model_validate(row) for row in usage_rows),
        events=tuple(EventEnvelope.model_validate(row) for row in event_rows),
    )


def persist_candidate(
    session: Session, candidate: SignalCandidate, *, seed: int
) -> event_orm.Signal | None:
    """Insert a candidate, or return `None` if an identical signal already exists.

    The surrogate id is derived from the dedupe key so a replay that *does* insert
    produces the same row identity it would have produced the first time. Detection
    stays reproducible end to end, not just at the business-key level.
    """
    statement = (
        insert(event_orm.Signal)
        .values(
            id=deterministic_uuid(seed, "signal", candidate.dedupe_key),
            signal_type=candidate.signal_type,
            detector_version=candidate.detector_version,
            severity=candidate.severity,
            account_id=candidate.account_id,
            opportunity_id=candidate.opportunity_id,
            detected_at=candidate.detected_at,
            dedupe_key=candidate.dedupe_key,
            evidence_refs=list(candidate.evidence_refs),
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(event_orm.Signal.id)
    )
    inserted_id = session.execute(statement).scalar_one_or_none()
    session.flush()
    if inserted_id is None:
        return None
    return session.get(event_orm.Signal, inserted_id)


def run_detectors(
    session: Session, *, evaluated_at: datetime, settings: Settings
) -> tuple[DetectionResult, list[event_orm.Signal]]:
    """Evaluate every implemented detector against every opportunity."""
    detectors = implemented_detectors(settings)
    opportunity_rows = session.scalars(
        sa.select(gtm_orm.Opportunity).order_by(gtm_orm.Opportunity.opportunity_ref)
    ).all()

    contexts = 0
    candidates = 0
    created: list[event_orm.Signal] = []

    for opportunity_row in opportunity_rows:
        context = build_detection_context(session, opportunity_row, evaluated_at=evaluated_at)
        if context is None:
            continue
        contexts += 1

        for detector in detectors:
            candidate = detector.evaluate(context)
            if candidate is None:
                continue
            candidates += 1
            signal = persist_candidate(session, candidate, seed=settings.seed)
            if signal is not None:
                created.append(signal)

    return (
        DetectionResult(
            contexts_evaluated=contexts, candidates=candidates, signals_created=len(created)
        ),
        created,
    )
