"""The detector contract.

Detectors are **pure and deterministic**: same inputs, same output, always. They
receive a `DetectionContext` and return a `SignalCandidate` or nothing. No I/O, no
LLM, no clock access except the `evaluated_at` passed in
(`docs/event-model.md` §4).

That last point is why `DetectionContext` is frozen and carries no session, no
repository, and no engine. A detector *cannot* perform I/O — not by convention, but
because it has nothing to perform it with.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from revenue_sentinel.core.errors import ConfigurationError
from revenue_sentinel.domain.enums import SignalType
from revenue_sentinel.domain.events import EventEnvelope
from revenue_sentinel.domain.gtm import Account, Opportunity, UsageSnapshot
from revenue_sentinel.domain.signals import SignalCandidate


@dataclass(frozen=True, slots=True)
class DetectionContext:
    """A read-only bundle of everything a detector may look at.

    `evaluated_at` is injected. "14 days ago" is 14 days from this instant, not from
    whenever the process happened to run, which is what makes the demo reproducible
    and these tests possible.
    """

    evaluated_at: datetime
    account: Account
    opportunity: Opportunity
    latest_sales_touch: datetime | None
    usage_window: tuple[UsageSnapshot, ...]
    events: tuple[EventEnvelope, ...]

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None:
            raise ConfigurationError("DetectionContext.evaluated_at must be timezone-aware")


@runtime_checkable
class Detector(Protocol):
    """A registered condition detector."""

    @property
    def signal_type(self) -> SignalType: ...

    @property
    def version(self) -> str: ...

    @property
    def window(self) -> timedelta: ...

    @property
    def is_implemented(self) -> bool:
        """False for the seven ROADMAP contracts.

        The registry holds eight detectors and one of them works. Making that
        difference a queryable property is what stops "eight detectors" being
        claimed anywhere -- the capability matrix and a test both read it.
        """
        ...

    def evaluate(self, context: DetectionContext) -> SignalCandidate | None:
        """Return a candidate signal, or `None` if the condition does not hold."""
        ...
