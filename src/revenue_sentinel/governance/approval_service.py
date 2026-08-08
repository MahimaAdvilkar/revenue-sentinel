"""Reading and deciding approvals by reference, for the CLI.

Thin on purpose. The rules live in `approvals.py`; this adds only what a caller at a
terminal needs -- lookup by `APR-001` rather than by UUID, and a view that carries the
*effective* status so a lapsed request is never listed as actionable.

`decide` is re-exported rather than reimplemented. Two places that both know how to
approve something is one place too many.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.errors import NotFoundError
from revenue_sentinel.db.models import governance as orm
from revenue_sentinel.db.models import investigation as inv_orm
from revenue_sentinel.domain.enums import ApprovalStatus
from revenue_sentinel.governance.approvals import decide, effective_status

__all__ = ["ApprovalView", "decide", "get_by_ref", "list_requests"]


@dataclass(frozen=True, slots=True)
class ApprovalView:
    """One approval request as a human should see it."""

    approval_ref: str
    effective_status: ApprovalStatus
    requested_by: str
    expires_at: datetime
    intervention_title: str


def get_by_ref(session: Session, approval_ref: str) -> orm.ApprovalRequest:
    request = session.scalar(
        sa.select(orm.ApprovalRequest).where(orm.ApprovalRequest.approval_ref == approval_ref)
    )
    if request is None:
        raise NotFoundError("approval request", approval_ref)
    return request


def list_requests(
    session: Session, *, now: datetime, pending_only: bool = True
) -> list[ApprovalView]:
    """Approval requests, newest first, with expiry applied at read time.

    `pending_only` filters on the **effective** status, so a request that lapsed an hour
    ago disappears from the actionable list without waiting for a sweeper.
    """
    rows = session.execute(
        sa.select(orm.ApprovalRequest, inv_orm.Intervention.title)
        .join(
            orm.PolicyEvaluation,
            orm.PolicyEvaluation.id == orm.ApprovalRequest.policy_evaluation_id,
        )
        .join(
            inv_orm.Intervention,
            inv_orm.Intervention.id == orm.PolicyEvaluation.intervention_id,
        )
        .order_by(orm.ApprovalRequest.requested_at.desc())
    ).all()

    views = [
        ApprovalView(
            approval_ref=request.approval_ref,
            effective_status=effective_status(request, now=now),
            requested_by=request.requested_by,
            expires_at=request.expires_at,
            intervention_title=title,
        )
        for request, title in rows
    ]

    if pending_only:
        return [view for view in views if view.effective_status is ApprovalStatus.PENDING]
    return views
