"""`GET /health` -- the only endpoint in Session 1.

The handler does transport work only (boundary R2): it asks the database whether it
is reachable, shapes a response, and picks a status code. It contains no domain
logic, because there is none to contain.

The endpoint reports **liveness and dependency reachability**, not correctness. It
does not assert that migrations are current or that the seed data is present; a
health check that quietly performs schema queries becomes a load-bearing part of
startup, and then a slow one.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict

from revenue_sentinel.db.session import database_is_reachable

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """The health payload. Typed so the Session 9 client can generate against it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok", "degraded"]
    version: str
    app_env: str
    demo_mode: str
    database: Literal["reachable", "unreachable"]


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A dependency is unreachable"}},
    summary="Liveness and dependency reachability",
)
def get_health(request: Request, response: Response) -> HealthResponse:
    """Report process health and whether PostgreSQL answers.

    Returns 503 when the database is unreachable so an orchestrator can act on the
    status code rather than having to parse the body.
    """
    reachable = database_is_reachable(request.app.state.engine)
    if not reachable:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    settings = request.app.state.settings
    return HealthResponse(
        status="ok" if reachable else "degraded",
        version=request.app.state.version,
        app_env=settings.app_env,
        demo_mode=settings.demo_mode,
        database="reachable" if reachable else "unreachable",
    )
