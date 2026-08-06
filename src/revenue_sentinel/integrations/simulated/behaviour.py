"""Deterministic latency and failure injection.

ADR-0004 left a debt: *"the simulated adapters must inject at least some realistic
failure -- latency, transient errors, missing fields -- so the retry and
error-handling paths are exercised rather than theoretical. An adapter that never
fails does not test the executor."*

This is that, with one constraint the ADR did not state and the demo requires:
**it must be deterministic.** A random failure rate would make the test suite flaky
and the demo unrepeatable, which is exactly the tradeoff `DEMO_MODE=fixture` exists to
avoid. So failures are *scripted* rather than sampled: the same call sequence produces
the same outcomes, every run, forever.

**Both are disabled by default.** Tests that exercise failure paths enable them
explicitly. Session 4 asserts the correct error code comes back; consuming it with a
retry is Session 6.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Final

from revenue_sentinel.core.errors import RevenueSentinelError

SCRIPT_SEPARATOR: Final = ","
SCRIPT_FIELD_SEPARATOR: Final = ":"
SCRIPT_ASSIGNMENT: Final = "="


class InjectedFailureError(RevenueSentinelError):
    """A simulated upstream failure, raised by an adapter on a scripted call."""

    def __init__(self, tool_name: str, ordinal: int, failure_kind: str) -> None:
        self.tool_name = tool_name
        self.ordinal = ordinal
        self.failure_kind = failure_kind
        super().__init__(f"simulated {failure_kind} on call {ordinal} to {tool_name}")


def parse_failure_script(script: str) -> dict[tuple[str, int], str]:
    """Parse `crm_get_account:3=ADAPTER_ERROR,support_get_open_issues:1=RATE_LIMITED`.

    Read as: the Nth call to that tool in this process fails with that kind.
    """
    parsed: dict[tuple[str, int], str] = {}
    for clause in script.split(SCRIPT_SEPARATOR):
        cleaned = clause.strip()
        if not cleaned:
            continue
        target, _, kind = cleaned.partition(SCRIPT_ASSIGNMENT)
        tool_name, _, ordinal = target.partition(SCRIPT_FIELD_SEPARATOR)
        if not tool_name or not ordinal.isdigit() or not kind:
            raise ValueError(
                f"malformed failure script clause {cleaned!r}; expected tool_name:ordinal=KIND"
            )
        parsed[(tool_name.strip(), int(ordinal))] = kind.strip()
    return parsed


@dataclass(slots=True)
class SimulatedBehaviour:
    """Per-process call counting, scripted failures, and fixed latency.

    Latency is a flat sleep rather than a distribution: a distribution would need a
    random source, and the point of this module is that there isn't one.
    """

    latency_ms: int = 0
    failure_script: dict[tuple[str, int], str] = field(default_factory=dict)
    _calls: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, *, latency_ms: int, failure_script: str) -> SimulatedBehaviour:
        return cls(
            latency_ms=latency_ms,
            failure_script=parse_failure_script(failure_script) if failure_script else {},
        )

    @property
    def is_inert(self) -> bool:
        """True when nothing will be injected -- the default."""
        return self.latency_ms == 0 and not self.failure_script

    def call_count(self, tool_name: str) -> int:
        return self._calls.get(tool_name, 0)

    def before_call(self, tool_name: str) -> None:
        """Count the call, sleep if configured, and raise if this one is scripted."""
        ordinal = self._calls.get(tool_name, 0) + 1
        self._calls[tool_name] = ordinal

        if self.latency_ms:
            time.sleep(self.latency_ms / 1000)

        kind = self.failure_script.get((tool_name, ordinal))
        if kind is not None:
            raise InjectedFailureError(tool_name, ordinal, kind)
