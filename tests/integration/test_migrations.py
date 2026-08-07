"""Acceptance criterion 3: one baseline creates everything, and downgrade empties it.

The round trip is the point. Autogenerate drops tables but not the PostgreSQL enum
types they used, so a naive downgrade leaves 26 orphaned types behind and the next
`upgrade` fails with "type already exists". These tests are what stop that shipping.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from revenue_sentinel.core.config import PROJECT_ROOT
from revenue_sentinel.db.models import Base

EXPECTED_TABLES = 29
EXPECTED_ENUM_TYPES = 27
"""26 through Session 4. Migration 0004 added `proposed_action`, so an intervention can
record a proposal the policy layer refused."""


def _alembic(command: list[str], url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell, no user input
        [sys.executable, "-m", "alembic", *command],
        cwd=PROJECT_ROOT,
        env={**os.environ, "ALEMBIC_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )


def _table_names(engine: Engine) -> set[str]:
    inspector = sa.inspect(engine)
    return set(inspector.get_table_names()) - {"alembic_version"}


def _enum_type_names(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                "SELECT t.typname FROM pg_type t "
                "JOIN pg_namespace n ON n.oid = t.typnamespace "
                "WHERE t.typtype = 'e' AND n.nspname = 'public'"
            )
        )
        return {row[0] for row in rows}


def test_baseline_creates_every_documented_table(engine: Engine) -> None:
    tables = _table_names(engine)
    assert len(tables) == EXPECTED_TABLES, sorted(tables)


def test_migrated_schema_matches_the_orm_metadata(engine: Engine) -> None:
    """The migration and the models must describe the same database.

    They are written separately and can drift; this is the check that notices.
    """
    assert _table_names(engine) == set(Base.metadata.tables)


def test_baseline_creates_every_native_enum_type(engine: Engine) -> None:
    assert len(_enum_type_names(engine)) == EXPECTED_ENUM_TYPES


def test_documented_constraints_and_indexes_exist(engine: Engine) -> None:
    inspector = sa.inspect(engine)

    unique_columns = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("raw_events")
    }
    assert ("source_system", "source_event_id") in unique_columns.values()

    transition_uniques = {
        tuple(c["column_names"]) for c in inspector.get_unique_constraints("workflow_transitions")
    }
    assert ("run_id", "sequence") in transition_uniques

    audit_indexes = {
        tuple(index["column_names"]) for index in inspector.get_indexes("audit_events")
    }
    assert ("incident_id", "occurred_at") in audit_indexes


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("action_records", "idempotency_key"),
        ("signals", "dedupe_key"),
    ],
)
def test_idempotency_columns_are_unique_in_the_database(
    engine: Engine, table: str, column: str
) -> None:
    """Prevented by a constraint, not by application logic (docs/data-model.md §4)."""
    inspector = sa.inspect(engine)
    unique_single = {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table)} | {
        tuple(i["column_names"]) for i in inspector.get_indexes(table) if i["unique"]
    }
    assert (column,) in unique_single


def test_downgrade_returns_to_empty_then_upgrade_restores(
    engine: Engine, migrated_database_url: str
) -> None:
    """Full round trip, including the enum types autogenerate forgets.

    Runs last-ish by name and restores the schema before returning, so the rest of
    the suite is unaffected.
    """
    down = _alembic(["downgrade", "base"], migrated_database_url)
    assert down.returncode == 0, f"{down.stdout}\n{down.stderr}"

    assert _table_names(engine) == set()
    assert _enum_type_names(engine) == set(), "enum types survived the downgrade"

    up = _alembic(["upgrade", "head"], migrated_database_url)
    assert up.returncode == 0, f"{up.stdout}\n{up.stderr}"

    assert len(_table_names(engine)) == EXPECTED_TABLES
    assert len(_enum_type_names(engine)) == EXPECTED_ENUM_TYPES


def test_autogenerate_detects_no_drift_from_the_models(migrated_database_url: str) -> None:
    """`alembic check` must report no pending changes.

    If this fails, someone edited a model without adding a revision -- the exact
    situation that makes a fresh clone and a developer's database disagree.
    """
    result = _alembic(["check"], migrated_database_url)
    assert result.returncode == 0, (
        "models and migrations have drifted; a new revision is needed:\n"
        f"{result.stdout}\n{result.stderr}"
    )
