"""Error types.

One base class so callers can catch everything this system raises without also
catching `Exception`. Subclasses are deliberately few: an error type earns its
existence by being caught somewhere, not by being descriptive.
"""

from __future__ import annotations


class RevenueSentinelError(Exception):
    """Base for every error raised by this application."""


class ConfigurationError(RevenueSentinelError):
    """Configuration is missing, malformed, or internally inconsistent.

    Raised at startup rather than at first use -- a misconfigured system should
    refuse to start, not fail halfway through a workflow run.
    """


class NotFoundError(RevenueSentinelError):
    """A record referenced by business key does not exist."""

    def __init__(self, entity: str, ref: str) -> None:
        self.entity = entity
        self.ref = ref
        super().__init__(f"{entity} not found: {ref}")


class DomainValidationError(RevenueSentinelError):
    """A domain invariant was violated.

    Distinct from `pydantic.ValidationError`, which covers shape. This covers
    rules that hold across fields -- for example, an at-risk value exceeding the
    weighted value it was derived from.
    """


class CalculationError(RevenueSentinelError):
    """A deterministic calculator was given inputs it refuses to compute on.

    Deliberately loud. `analytics/` produces the figures the product is judged on,
    so a nonsensical input raises rather than returning a plausible-looking zero.
    """
