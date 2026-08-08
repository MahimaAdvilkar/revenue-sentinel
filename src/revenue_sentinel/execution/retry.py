"""What the executor retries, and what it must never retry.

**The executor does not use `ERROR_POLICY[...].retry`, and that is deliberate.** That
flag is *agent* guidance: `INVALID_ARGUMENTS` carries `retry=True` because an agent that
sent malformed arguments should fix them and try again. An executor has no such option --
its arguments come from a persisted intervention, so re-sending them unchanged would
produce the identical failure forever.

So there are two different notions of "retryable" in this system, and conflating them
would be a real bug. `RETRYABLE_BY_EXECUTOR` below is the narrow one, and a test asserts
the two sets are deliberately different rather than accidentally divergent.

Backoff is deterministic -- no jitter (ADR-0007). Jitter exists to de-synchronise many
clients hammering one service; this system runs one workflow at a time, so jitter would
buy nothing and cost reproducibility.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from revenue_sentinel.mcp.errors import ToolErrorCode

MAX_ATTEMPTS: Final = 3
"""Three attempts total, not three retries. Beyond that a transient fault is not
transient, and continuing to hammer a struggling adapter makes it worse."""

BASE_DELAY_MS: Final = 50

RETRYABLE_BY_EXECUTOR: Final[frozenset[ToolErrorCode]] = frozenset(
    {
        ToolErrorCode.RATE_LIMITED,
        ToolErrorCode.ADAPTER_ERROR,
    }
)
"""Only genuinely transient faults.

Explicitly **not** retryable, each for its own reason:

* `POLICY_DENIED` -- retrying a refusal is the failure mode the policy layer exists to
  prevent. So is routing around it.
* `APPROVAL_REQUIRED` -- the answer changes when a person acts, not when we ask again.
* `INVALID_ARGUMENTS` -- the arguments are persisted; re-sending them cannot help.
* `NOT_FOUND` -- the entity does not exist. Asking twice will not conjure it.
* `BUDGET_EXCEEDED` -- retrying a budget refusal is how a budget stops being a budget.
  (No producer until Session 7; listed so it is refused the moment there is one.)
"""


def is_retryable(code: ToolErrorCode) -> bool:
    return code in RETRYABLE_BY_EXECUTOR


def backoff_ms(attempt: int) -> int:
    """`50, 100, 200, ...` -- doubling, deterministic, no jitter.

    `attempt` is 1-based, so the delay *before* attempt 2 is `backoff_ms(1)`.
    """
    if attempt < 1:
        raise ValueError(f"attempt must be 1-based, got {attempt}")
    return int(BASE_DELAY_MS * (2 ** (attempt - 1)))


SleepFn = Callable[[float], None]


def no_sleep(_seconds: float) -> None:
    """The sleep used by tests and by fixture mode.

    Backoff timing is not a behaviour worth asserting, and a suite that actually slept
    would pay for that opinion on every run.
    """
    return None
