"""Detector output.

A `Signal` is what a detector emits; an `Incident` (see `incidents.py`) is the unit
of work it opens. `dedupe_key` is the first idempotency boundary in the system:
re-ingesting the same event window cannot open a second incident for the same
condition, because the column is UNIQUE.
"""

from __future__ import annotations

from uuid import UUID

from revenue_sentinel.domain.base import Digest, DomainModel, NonEmptyStr, UtcDatetime
from revenue_sentinel.domain.enums import Severity, SignalType


class SignalCandidate(DomainModel):
    """What a detector returns: a signal minus its surrogate key.

    Detectors do not mint identifiers. If `evaluate()` returned a `Signal` with a
    fresh UUID, calling it twice on identical input would produce different
    objects and the purity guarantee in `docs/event-model.md` §4 would be
    untestable. Identity is assigned by the dispatcher at persistence time, where
    it belongs.
    """

    signal_type: SignalType
    detector_version: NonEmptyStr
    severity: Severity
    account_id: UUID
    opportunity_id: UUID | None = None
    detected_at: UtcDatetime
    dedupe_key: Digest
    evidence_refs: tuple[str, ...] = ()


class Signal(DomainModel):
    """A detected condition.

    `detector_version` is part of the dedupe key: retuning a detector is allowed to
    produce a new signal for a condition an earlier version already reported,
    because the two are not the same claim.
    """

    id: UUID
    signal_type: SignalType
    detector_version: NonEmptyStr
    severity: Severity
    account_id: UUID
    opportunity_id: UUID | None = None
    detected_at: UtcDatetime
    dedupe_key: Digest
    evidence_refs: tuple[str, ...] = ()
