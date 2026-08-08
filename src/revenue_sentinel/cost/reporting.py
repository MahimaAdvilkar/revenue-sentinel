"""Lookups the CLI needs. Kept out of `summary.py` so that module stays free of joins."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.errors import NotFoundError
from revenue_sentinel.db.models import workflow as workflow_orm


def latest_run_id(session: Session, incident_ref: str) -> UUID:
    """The most recent run for an incident. Raises rather than returning `None`."""
    run_id = session.scalar(
        sa.select(workflow_orm.WorkflowRun.id)
        .join(
            workflow_orm.Incident,
            workflow_orm.Incident.id == workflow_orm.WorkflowRun.incident_id,
        )
        .where(workflow_orm.Incident.incident_ref == incident_ref)
        .order_by(workflow_orm.WorkflowRun.started_at.desc())
    )
    if run_id is None:
        raise NotFoundError("workflow run", incident_ref)
    return run_id
