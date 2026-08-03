"""Engine and session management.

Synchronous SQLAlchemy 2.0 -- see ADR-0009. At this scale async buys no throughput
and costs real complexity in migrations, tests, and the seeder; FastAPI runs
synchronous handlers in a threadpool, so the API surface is unaffected.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from revenue_sentinel.core.config import Settings, get_settings


def build_engine(settings: Settings | None = None, *, echo: bool = False) -> Engine:
    """Create an engine from configuration.

    `pool_pre_ping` costs one round trip per checkout and removes an entire class of
    "connection was closed by the server" failures after a container restart, which
    is a normal occurrence in local development.
    """
    resolved = settings or get_settings()
    return create_engine(
        resolved.database_url,
        echo=echo,
        pool_pre_ping=True,
        future=True,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Session factory bound to an engine.

    `expire_on_commit=False` so domain objects read from a committed session remain
    usable afterwards, rather than triggering a lazy reload against a closed session.
    """
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """A transactional scope: commit on success, roll back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def database_is_reachable(engine: Engine) -> bool:
    """One cheap round trip, used by the health endpoint.

    Swallows the exception deliberately: the caller wants a boolean for a status
    payload, not a stack trace. Anything that needs the detail logs it at the call
    site, where there is a request to attach it to.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True
