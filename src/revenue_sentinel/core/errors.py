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


class FixtureMissError(RevenueSentinelError):
    """`DEMO_MODE=fixture` was asked for a response that has not been recorded.

    Raised, never fallen back from. A silent fallback would turn an offline test into
    a billable network call the first time a prompt changed -- quietly, in CI, and
    possibly during a demo (ADR-0007).
    """

    def __init__(self, node_name: str, digest: str, expected_path: str) -> None:
        self.node_name = node_name
        self.digest = digest
        self.expected_path = expected_path
        super().__init__(
            f"no recorded response for node {node_name!r} (digest {digest}). "
            f"Expected: {expected_path}. Fixture mode does not fall back to a live "
            f"call -- regenerate with `make record` if the prompt changed."
        )


class StructuredOutputError(RevenueSentinelError):
    """Model output failed schema validation.

    Distinct from a transport failure: the call succeeded and returned something we
    refuse to use. There is no free-text parsing fallback (rule 4).
    """


class FabricatedCitationError(RevenueSentinelError):
    """A hypothesis cited evidence that does not exist in workflow state.

    The anti-hallucination gate. The run fails and nothing is persisted -- a
    fabricated justification never reaches the database, let alone a screen.
    """

    def __init__(self, hypothesis_ref: str, unknown_refs: tuple[str, ...]) -> None:
        self.hypothesis_ref = hypothesis_ref
        self.unknown_refs = unknown_refs
        super().__init__(
            f"{hypothesis_ref} cites evidence that does not exist: "
            f"{', '.join(sorted(unknown_refs))}"
        )
