"""FastAPI application factory.

The app is built by a function rather than declared at import time so tests can
construct one with an isolated engine. A module-level `app` still exists because
`uvicorn revenue_sentinel.api.main:app` is the documented run command.

Four routes as of Session 2: `/health`, `POST /ingest`, `GET /incidents`, and
`GET /incidents/{incident_ref}`. Approval endpoints arrive in Session 6.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as package_version
from typing import Final

from fastapi import FastAPI
from sqlalchemy import Engine

from revenue_sentinel.api.dashboard import router as dashboard_router
from revenue_sentinel.api.health import router as health_router
from revenue_sentinel.api.incidents import router as incidents_router
from revenue_sentinel.api.ingest import router as ingest_router
from revenue_sentinel.core.config import Settings, get_settings
from revenue_sentinel.core.logging import configure_logging, get_logger
from revenue_sentinel.db.session import build_engine, build_session_factory

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Dispose the connection pool on shutdown."""
    yield
    engine: Engine = app.state.engine
    engine.dispose()


def create_app(*, settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Build the application.

    Both dependencies are injectable so an integration test can point the app at a
    throwaway database without mutating process-wide configuration.
    """
    resolved_settings = settings or get_settings()
    configure_logging(level=resolved_settings.log_level, log_format=resolved_settings.log_format)

    app = FastAPI(
        title="Revenue Sentinel",
        description=(
            "Agentic AI GTM Control Tower. Every external integration is SIMULATED "
            "in v1 -- see CAPABILITY_MATRIX.md."
        ),
        version=package_version("revenue-sentinel"),
        lifespan=_lifespan,
    )

    resolved_engine = engine or build_engine(resolved_settings)
    app.state.settings = resolved_settings
    app.state.engine = resolved_engine
    app.state.session_factory = build_session_factory(resolved_engine)
    app.state.version = package_version("revenue-sentinel")

    app.include_router(health_router)
    app.include_router(ingest_router)
    app.include_router(incidents_router)
    app.include_router(dashboard_router)

    logger.info(
        "application_configured",
        app_env=resolved_settings.app_env,
        demo_mode=resolved_settings.demo_mode,
        routes=len(app.routes),
    )
    return app


_APP_ATTRIBUTE: Final = "app"
_cached_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    """Build the module-level `app` on first access, not at import time.

    `uvicorn revenue_sentinel.api.main:app` resolves the name through this hook, so
    the documented run command is unchanged. Importing the module no longer opens a
    connection pool or requires DATABASE_URL to be set, which is what lets the unit
    tests import it without a database.
    """
    if name != _APP_ATTRIBUTE:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    global _cached_app
    if _cached_app is None:
        _cached_app = create_app()
    return _cached_app
