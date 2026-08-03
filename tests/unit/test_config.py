"""Configuration loading and validation.

The most valuable test here is the last one: it asserts that `.env.example` and the
`Settings` class agree. A committed template that documents a variable nothing reads
is worse than no template, because it looks authoritative.
"""

from __future__ import annotations

import os
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from revenue_sentinel.core.config import PROJECT_ROOT, Settings

VALID_URL = "postgresql+psycopg://sentinel:local@localhost:55432/revenue_sentinel"

# Names in `.env.example` that are deliberately not application settings.
COMPOSE_ONLY = {
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_HOST",
    "POSTGRES_HOST_PORT",
}
FRONTEND_ONLY = {"NEXT_PUBLIC_API_BASE_URL"}


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must not inherit the developer's `.env` or CI's exported values.

    Without this, what a test proves depends on the machine it runs on -- which is
    the opposite of what a configuration test is for.
    """
    settings_names = {name.upper() for name in Settings.model_fields}
    for name in list(os.environ):
        if name.upper() in settings_names:
            monkeypatch.delenv(name, raising=False)


def build(**overrides: object) -> Settings:
    """Construct settings from explicit values only -- no `.env`, no environment."""
    payload: dict[str, object] = {"database_url": VALID_URL}
    payload.update(overrides)
    return Settings(_env_file=None, **payload)


def build_from_nothing() -> Settings:
    return Settings(_env_file=None)


def test_defaults_match_the_committed_template() -> None:
    settings = build()
    assert settings.demo_mode == "fixture"
    assert settings.app_env == "local"
    assert settings.seed == 20260801
    assert settings.budget_run_usd == Decimal("0.50")
    assert settings.detector_inactivity_days == 14
    assert settings.policy_version == "v1"


def test_database_url_is_required() -> None:
    """No default. A missing URL must stop the process rather than fall back to
    localhost:5432, which on the development machine is a different database."""
    with pytest.raises(ValidationError):
        build_from_nothing()


def test_database_url_must_pin_the_psycopg_driver() -> None:
    """A bare `postgresql://` resolves to psycopg2, which is not installed."""
    with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
        build(database_url="postgresql://sentinel:local@localhost:55432/revenue_sentinel")


def test_evaluation_timestamp_is_timezone_aware_and_utc() -> None:
    stamp = build().evaluation_timestamp
    assert stamp.tzinfo is not None
    assert stamp.utcoffset() == timedelta(0)


def test_naive_evaluation_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        build(evaluation_timestamp="2026-08-01T12:00:00")


@pytest.mark.parametrize("mode", ["live", "record"])
def test_billable_demo_modes_require_an_api_key(mode: str) -> None:
    """A mode that spends money must not start without the credential it needs."""
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        build(demo_mode=mode)


def test_fixture_mode_needs_no_api_key() -> None:
    assert build(demo_mode="fixture").anthropic_api_key is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_api_key_counts_as_absent(blank: str) -> None:
    """`.env.example` ships `ANTHROPIC_API_KEY=` empty. An empty string must not
    satisfy the credential check for a billable mode."""
    assert build(anthropic_api_key=blank).anthropic_api_key is None
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        build(demo_mode="live", anthropic_api_key=blank)


def test_api_key_is_wrapped_so_it_cannot_be_printed_by_accident() -> None:
    """`SecretStr` keeps the key out of logs, tracebacks, and error messages.

    The placeholder deliberately avoids the real `sk-ant-` prefix: the CI secret
    scan greps the whole tree for that pattern, and a test fixture that trips the
    scanner would train everyone to ignore it.
    """
    placeholder = "placeholder-not-a-real-credential"
    settings = build(demo_mode="live", anthropic_api_key=placeholder)

    assert placeholder not in repr(settings)
    assert placeholder not in str(settings)
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == placeholder


@pytest.mark.parametrize("mode", ["offline", "", "FIXTURE"])
def test_unknown_demo_mode_is_rejected(mode: str) -> None:
    with pytest.raises(ValidationError):
        build(demo_mode=mode)


@pytest.mark.parametrize(
    "field",
    [
        "limit_model_calls_per_run",
        "limit_tool_calls_per_run",
        "limit_node_executions_per_run",
        "limit_run_wallclock_seconds",
        "approval_expiry_hours",
    ],
)
def test_non_monetary_ceilings_must_be_positive(field: str) -> None:
    """A ceiling of zero would halt every run; a negative one is nonsense."""
    with pytest.raises(ValidationError):
        build(**{field: 0})


def test_settings_are_immutable() -> None:
    settings = build()
    with pytest.raises(ValidationError):
        settings.seed = 1  # type: ignore[misc]


def _template_variable_names() -> set[str]:
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    names: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", stripped)
        if match:
            names.add(match.group(1))
    return names


def test_env_example_and_settings_do_not_drift() -> None:
    """Every documented variable is either a setting or explicitly out of scope."""
    documented = _template_variable_names()
    assert documented, ".env.example parsed to zero variables -- the parser is wrong"

    fields = {name.upper() for name in Settings.model_fields}
    unexplained = documented - fields - COMPOSE_ONLY - FRONTEND_ONLY
    assert not unexplained, f".env.example documents variables nothing reads: {sorted(unexplained)}"


def test_every_setting_is_documented_in_the_template() -> None:
    documented = _template_variable_names()
    fields = {name.upper() for name in Settings.model_fields}
    undocumented = fields - documented
    assert not undocumented, f"settings missing from .env.example: {sorted(undocumented)}"


def test_project_root_resolves_to_the_repository() -> None:
    assert isinstance(PROJECT_ROOT, Path)
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert (PROJECT_ROOT / "fixtures" / "seed" / "accounts.json").is_file()
