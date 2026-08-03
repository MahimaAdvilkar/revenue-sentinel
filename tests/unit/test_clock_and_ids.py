"""Clock injection and identifier generation.

`test_no_source_module_reads_the_wall_clock` is the load-bearing one. The demo's
reproducibility rests on evaluation time being injected rather than read, and that is
a property of the whole source tree, not of any single function -- so it is checked
across the whole source tree.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from revenue_sentinel.core.clock import Clock, FrozenClock, SystemClock, ensure_utc
from revenue_sentinel.core.config import PROJECT_ROOT
from revenue_sentinel.core.errors import ConfigurationError, DomainValidationError
from revenue_sentinel.core.ids import (
    account_ref,
    deterministic_uuid,
    evidence_ref,
    format_ref,
    hypothesis_ref,
    incident_ref,
    new_id,
    opportunity_ref,
    parse_ref,
)

INSTANT = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def test_frozen_clock_returns_the_injected_instant() -> None:
    clock = FrozenClock(INSTANT)
    assert clock.now() == INSTANT
    assert clock.now() == clock.now()


def test_frozen_clock_normalises_to_utc() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 21, 0, tzinfo=timezone(timedelta(hours=9))))
    assert clock.now() == INSTANT
    assert clock.now().tzinfo is UTC


def test_frozen_clock_rejects_a_naive_instant() -> None:
    with pytest.raises(ConfigurationError, match="timezone-aware"):
        FrozenClock(datetime(2026, 8, 1, 12, 0))  # noqa: DTZ001 -- the point of the test


def test_frozen_clock_cannot_be_mutated_into_a_moving_target() -> None:
    clock = FrozenClock(INSTANT)
    with pytest.raises((AttributeError, TypeError)):
        clock.instant = INSTANT + timedelta(days=1)  # type: ignore[misc]


def test_both_clocks_satisfy_the_protocol() -> None:
    assert isinstance(FrozenClock(INSTANT), Clock)
    assert isinstance(SystemClock(), Clock)


def test_system_clock_returns_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC


def test_ensure_utc_rejects_naive_and_converts_aware() -> None:
    with pytest.raises(ConfigurationError, match="naive datetime"):
        ensure_utc(datetime(2026, 8, 1, 12, 0))  # noqa: DTZ001 -- the point of the test
    converted = ensure_utc(datetime(2026, 8, 1, 7, 0, tzinfo=timezone(timedelta(hours=-5))))
    assert converted == INSTANT


def _source_modules() -> list[Path]:
    return sorted((PROJECT_ROOT / "src" / "revenue_sentinel").rglob("*.py"))


def test_no_source_module_reads_the_wall_clock_except_system_clock() -> None:
    """Evaluation time is injected, never read (docs/event-model.md §4).

    `SystemClock` is the single sanctioned caller. Anything else reaching for
    `datetime.now()` would silently make the demo non-reproducible, and the failure
    would look like flakiness rather than like a bug.
    """
    offenders: list[str] = []
    for path in _source_modules():
        if path.name == "clock.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {"now", "utcnow", "today"} and isinstance(
                node.func.value, ast.Name | ast.Attribute
            ):
                target = ast.unparse(node.func)
                if target.startswith(("datetime", "date")):
                    rel = path.relative_to(PROJECT_ROOT)
                    offenders.append(f"{rel}:{node.lineno}: {target}()")

    assert not offenders, "wall-clock access outside core/clock.py:\n  " + "\n  ".join(offenders)


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------
def test_deterministic_uuid_is_stable_for_the_same_seed_and_key() -> None:
    first = deterministic_uuid(20260801, "account", "ACC-1001")
    second = deterministic_uuid(20260801, "account", "ACC-1001")
    assert first == second


def test_deterministic_uuid_changes_with_the_seed() -> None:
    assert deterministic_uuid(20260801, "account", "ACC-1001") != deterministic_uuid(
        1, "account", "ACC-1001"
    )


def test_deterministic_uuid_changes_with_the_key() -> None:
    assert deterministic_uuid(20260801, "account", "ACC-1001") != deterministic_uuid(
        20260801, "account", "ACC-1002"
    )


def test_deterministic_uuid_is_independent_of_call_order() -> None:
    """Row identity must not depend on the order the seeder happens to insert in."""
    forward = [deterministic_uuid(7, "account", ref) for ref in ("ACC-1001", "ACC-1002")]
    backward = [deterministic_uuid(7, "account", ref) for ref in ("ACC-1002", "ACC-1001")]
    assert forward == list(reversed(backward))


def test_deterministic_uuid_requires_a_key() -> None:
    with pytest.raises(DomainValidationError):
        deterministic_uuid(20260801)


def test_new_id_is_random() -> None:
    assert new_id() != new_id()


@pytest.mark.parametrize(
    ("helper", "number", "expected"),
    [
        (account_ref, 1001, "ACC-1001"),
        (opportunity_ref, 2001, "OPP-2001"),
        (incident_ref, 1, "INC-001"),
        (evidence_ref, 3, "EV-003"),
        (hypothesis_ref, 1, "HYP-001"),
    ],
)
def test_reference_formatting(helper: object, number: int, expected: str) -> None:
    assert helper(number) == expected  # type: ignore[operator]


def test_format_ref_rejects_a_negative_number() -> None:
    with pytest.raises(DomainValidationError, match="non-negative"):
        format_ref("ACC", -1, width=4)


def test_parse_ref_round_trips() -> None:
    assert parse_ref("ACC-1001") == ("ACC", 1001)
    assert parse_ref(account_ref(9999)) == ("ACC", 9999)


@pytest.mark.parametrize("bad", ["ACC1001", "acc-1001", "A-1", "ACC-", "-1001", "ACC-abc", ""])
def test_parse_ref_rejects_malformed_input(bad: str) -> None:
    """References arriving from fixtures or external systems are untrusted."""
    with pytest.raises(DomainValidationError, match="malformed"):
        parse_ref(bad)
