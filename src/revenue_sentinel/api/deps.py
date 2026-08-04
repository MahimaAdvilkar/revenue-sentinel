"""Request-scoped dependencies.

One transactional session per request: commit on success, roll back on any
exception. The boundary is explicit here rather than implicit in each handler, so a
route cannot leave a half-applied write behind by forgetting to commit.

Handlers that use this stay `def`, not `async def` (ADR-0009). Starlette runs them
in its threadpool; an `async def` handler would block the event loop on every query.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from revenue_sentinel.core.config import Settings


def get_settings_from_app(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    """Yield a session inside a transaction scoped to this request."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
