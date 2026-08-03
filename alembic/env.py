"""Alembic environment.

The database URL comes from application configuration, never from `alembic.ini`, so
migrations and the application can never disagree about which database they mean.

Importing `revenue_sentinel.db.models` is what populates `Base.metadata`. A model
that is not reachable from that package is invisible to autogenerate -- which is why
its `__init__` lists every table explicitly rather than using a wildcard.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from revenue_sentinel.core.config import get_settings
from revenue_sentinel.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the target database.

    `ALEMBIC_DATABASE_URL` wins when set, so the test suite can migrate an isolated
    database without mutating process-wide settings. Otherwise the application's
    configured `DATABASE_URL` is used.
    """
    override = os.environ.get("ALEMBIC_DATABASE_URL")
    if override:
        return override
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
