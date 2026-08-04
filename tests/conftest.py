"""Shared test fixtures.

Integration tests run against a **separate database** -- `<configured name>_test` --
created and migrated once per session and dropped at the end. `make test` therefore
never touches the seeded development database, which matters because the demo
depends on that database still holding the golden scenario afterwards.

Each test gets a session joined to an outer transaction that is rolled back on
teardown, so tests see a migrated-but-empty schema and cannot leak state into each
other even when the code under test commits.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import PROJECT_ROOT, Settings, get_settings

TEST_DB_SUFFIX = "_test"


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Application settings, loaded once."""
    return get_settings()


@pytest.fixture(scope="session")
def evaluation_timestamp(settings: Settings) -> datetime:
    """The frozen instant the whole fixture set is expressed relative to."""
    return settings.evaluation_timestamp


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


def _test_database_url(settings: Settings) -> URL:
    url = make_url(settings.database_url)
    return url.set(database=f"{url.database}{TEST_DB_SUFFIX}")


def _admin_url(settings: Settings) -> URL:
    """A URL for the maintenance database, used only to CREATE/DROP the test one."""
    return make_url(settings.database_url).set(database="postgres")


def _recreate_test_database(settings: Settings) -> URL:
    target = _test_database_url(settings)
    admin = sa.create_engine(_admin_url(settings), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        # Terminate stragglers first: a leftover connection from an interrupted run
        # makes DROP DATABASE hang rather than fail, which is a confusing way to
        # spend ten minutes.
        connection.execute(
            sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": target.database},
        )
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{target.database}"'))
        connection.execute(sa.text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()
    return target


def _drop_test_database(settings: Settings) -> None:
    target = _test_database_url(settings)
    admin = sa.create_engine(_admin_url(settings), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(
            sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": target.database},
        )
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def migrated_database_url(settings: Settings) -> Iterator[str]:
    """Create the test database, migrate it to head, drop it afterwards.

    Migrations run through the real Alembic CLI rather than
    `Base.metadata.create_all`. Those two can disagree, and the one that ships is
    Alembic -- testing the other would prove nothing about `make migrate`.
    """
    target = _recreate_test_database(settings)
    url = target.render_as_string(hide_password=False)

    environment = {**os.environ, "ALEMBIC_DATABASE_URL": url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _drop_test_database(settings)
        pytest.fail(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}")

    yield url
    _drop_test_database(settings)


@pytest.fixture(scope="session")
def engine(migrated_database_url: str) -> Iterator[Engine]:
    """Engine bound to the migrated test database."""
    created = sa.create_engine(migrated_database_url, pool_pre_ping=True)
    yield created
    created.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session inside a transaction that is always rolled back.

    `join_transaction_mode="create_savepoint"` means code under test can call
    `commit()` normally -- it lands on a savepoint, and the outer transaction still
    unwinds on teardown. Tests get real commit semantics with no shared state.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def seeded_session(db_session: Session, settings: Settings) -> Session:
    """A session with the full fixture set loaded, inside the rolled-back transaction.

    Uses the configured SEED and EVALUATION_TIMESTAMP so tests assert against the
    same data the demo runs on, not a variant of it.

    Also restarts `incident_ref_seq`. Sequence allocation is deliberately *not*
    transactional -- that is what makes it safe under concurrency -- so without this
    the first test to open an incident would get `INC-001` and every later one a
    different number, making assertions depend on test ordering. `ALTER SEQUENCE
    ... RESTART` is transactional and unwinds with the surrounding rollback.
    """
    from revenue_sentinel.db.seeding import seed_database

    db_session.execute(sa.text("ALTER SEQUENCE incident_ref_seq RESTART WITH 1"))
    seed_database(db_session, seed=settings.seed, evaluated_at=settings.evaluation_timestamp)
    return db_session
