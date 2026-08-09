"""The OpenAPI export, which the frontend/backend contract is generated from (ADR-0023).

The regression these tests exist for: the export used to call `get_settings()`, so it
required a configured `DATABASE_URL` it never connected to. That passed everywhere a
`.env` file or an exported variable happened to exist -- a developer machine, a fresh
clone with the variable set by hand -- and failed on the one CI job whose entire premise
is that it needs no database. The contract-drift gate could not run at all.

So the property under test is not "the export works". It is **the export does not depend
on runtime configuration**, which is the thing that was quietly untrue.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import export_openapi

from revenue_sentinel.core.config import PROJECT_ROOT


def test_export_does_not_read_runtime_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """`get_settings()` must not be reachable from the export path.

    Asserted by making it explode, which is the only way to reproduce the CI environment
    from inside this repository: `Settings` resolves `.env` by **absolute path**, so
    neither changing directory nor unsetting `DATABASE_URL` removes the configuration a
    developer machine has. That is precisely why the defect survived every local run and
    every fresh-clone run where the variable was exported by hand, and surfaced only on a
    runner that had neither.
    """

    def _explode() -> None:
        raise AssertionError("schema export must not read environment configuration")

    monkeypatch.setattr("revenue_sentinel.core.config.get_settings", _explode)
    monkeypatch.setattr("revenue_sentinel.api.main.get_settings", _explode)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    schema = export_openapi.build_schema()

    assert schema["paths"], "the export produced a document with no paths"


def test_export_settings_never_name_a_reachable_database() -> None:
    """The placeholder is inert, and says so in its own value."""
    settings = export_openapi.schema_settings()

    assert settings.database_url == export_openapi.UNUSED_DATABASE_URL
    assert "schema-export" in settings.database_url
    assert "unused" in settings.database_url


def test_export_ignores_a_configured_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured environment must not change the document either.

    The contract is checked in, so an export that varied with local configuration would
    make `git diff` noisy for reasons unrelated to the API -- and the drift gate would
    then be failing on the wrong thing.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://someone@elsewhere/other")

    assert export_openapi.render(export_openapi.build_schema()) == (
        PROJECT_ROOT / "apps/web/generated/openapi.json"
    ).read_text(encoding="utf-8")


def test_the_committed_contract_is_current() -> None:
    """The local half of the CI drift gate (ADR-0023).

    `make generate-api-types` regenerates this; a diff here means the API moved and the
    contract was not regenerated.
    """
    committed = (PROJECT_ROOT / "apps/web/generated/openapi.json").read_text(encoding="utf-8")

    assert export_openapi.render(export_openapi.build_schema()) == committed


def test_the_rendering_is_byte_stable() -> None:
    """Sorted keys and fixed indentation, so regenerating twice cannot produce a diff."""
    first = export_openapi.render(export_openapi.build_schema())
    second = export_openapi.render(export_openapi.build_schema())

    assert first == second
    assert first.endswith("\n")
    assert json.loads(first) == json.loads(second)


def test_the_target_path_is_where_the_frontend_reads_from() -> None:
    """A moved target would leave the frontend building against a file nobody updates."""
    assert Path("apps/web/generated/openapi.json") == export_openapi.TARGET
    assert (PROJECT_ROOT / export_openapi.TARGET).is_file()
