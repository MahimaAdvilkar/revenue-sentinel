"""Time access.

Every timestamp the system reasons about is *injected*, never read from the
process clock at the point of use. This is what makes detectors unit-testable and
the demo reproducible: "14 days ago" is 14 days from a fixed reference instant, not
from whenever the test happened to run.

`SystemClock` is the single sanctioned caller of `datetime.now`. A unit test greps
the source tree to keep it that way -- see `tests/unit/test_clock_and_ids.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from revenue_sentinel.core.errors import ConfigurationError


@runtime_checkable
class Clock(Protocol):
    """A source of the current instant, always timezone-aware and in UTC."""

    def now(self) -> datetime:
        """Return the current instant as a tz-aware UTC datetime."""
        ...


@dataclass(frozen=True, slots=True)
class FrozenClock:
    """A clock pinned to a single instant.

    Used by tests, the seeder, and the offline demo. Frozen and slotted so it
    cannot be mutated into a moving target partway through a run.
    """

    instant: datetime

    def __post_init__(self) -> None:
        if self.instant.tzinfo is None:
            raise ConfigurationError("FrozenClock requires a timezone-aware instant")

    def now(self) -> datetime:
        return self.instant.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SystemClock:
    """The real clock. The only place `datetime.now` is called."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize a tz-aware datetime to UTC, rejecting naive input.

    Naive datetimes are rejected rather than assumed-UTC: an assumption here shows
    up later as an off-by-hours bug in a "days since last activity" calculation.
    """
    if value.tzinfo is None:
        raise ConfigurationError(f"naive datetime is not permitted: {value!r}")
    return value.astimezone(UTC)
