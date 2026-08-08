"""Approval requests: created when policy says a person must decide.

**Nothing here executes anything, and nothing here approves anything.** Session 5
creates the request and reads its state. The approve/reject endpoints and the graph
interrupt that waits on one are Session 6.

Three properties, each with a test:

* **Expiry is evaluated on read.** A request whose `expires_at` has passed reports as
  `EXPIRED` even if no sweeper has run. An approval that has quietly lapsed must not be
  able to authorise anything just because a background job is late.
* **Self-approval is impossible.** The actor that requested cannot be the actor that
  decides. This is checked here rather than in a route handler, so it holds for every
  caller including the CLI.

  It compares `requested_by`, a real column as of migration 0005. Session 5 smuggled the
  actor into `decision_note` and parsed it back out; that worked, but it put an
  authorisation-relevant value in a free-text field where the next note would destroy it.

  **This prevents an accident, not an impersonation.** There is no authentication in this
  system: the actor is a string a caller supplies (ADR-0018).
* **Time is injected.** `occurred_at` is passed in, never read from the clock, which is
  what lets expiry be tested without sleeping and what keeps a replayed run identical.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.errors import RevenueSentinelError
from revenue_sentinel.core.ids import new_id
from revenue_sentinel.db.models import governance as orm
from revenue_sentinel.domain.enums import ApprovalStatus

APPROVAL_REF_SEQUENCE: Final = "approval_ref_seq"

DEFAULT_APPROVAL_TTL: Final = timedelta(hours=24)
"""Long enough for a working day, short enough that a forgotten request expires rather
than sitting approvable forever. Configurable per call; the default is the policy."""


class SelfApprovalError(RevenueSentinelError):
    """The requesting actor tried to decide their own approval request."""

    def __init__(self, actor: str) -> None:
        self.actor = actor
        super().__init__(
            f"{actor} requested this approval and cannot also decide it. "
            f"Approval requires a second person."
        )


class ApprovalExpiredError(RevenueSentinelError):
    """A decision was attempted on a request that had already lapsed."""

    def __init__(self, request_id: UUID, expires_at: datetime) -> None:
        super().__init__(f"approval request {request_id} expired at {expires_at.isoformat()}")


def create_approval_request(
    session: Session,
    *,
    policy_evaluation_id: UUID,
    run_id: UUID,
    requested_by: str,
    occurred_at: datetime,
    ttl: timedelta = DEFAULT_APPROVAL_TTL,
) -> orm.ApprovalRequest:
    """Record that a person must decide before this action could ever run.

    `requested_by` is a real column and `approval_ref` (`APR-001`) is allocated from a
    sequence, so a human at a CLI has something to type.
    """
    request = orm.ApprovalRequest(
        id=new_id(),
        approval_ref=allocate_approval_ref(session),
        policy_evaluation_id=policy_evaluation_id,
        run_id=run_id,
        status=ApprovalStatus.PENDING,
        requested_by=requested_by,
        requested_at=occurred_at,
        expires_at=occurred_at + ttl,
        decided_at=None,
        decided_by=None,
        decision_note=None,
    )
    session.add(request)
    session.flush()
    return request


def allocate_approval_ref(session: Session) -> str:
    """`APR-001`, from a sequence -- the same pattern incident references use.

    A sequence rather than `count(*) + 1`, which races under any concurrency and passes
    every single-threaded test.
    """
    number = session.execute(
        sa.select(sa.func.nextval(sa.text(f"'{APPROVAL_REF_SEQUENCE}'")))
    ).scalar_one()
    return f"APR-{int(number):03d}"


def effective_status(request: orm.ApprovalRequest, *, now: datetime) -> ApprovalStatus:
    """The status as it should be read, not merely as it was last written.

    A pending request past its expiry is `EXPIRED`. Callers use this rather than
    `request.status`, so a lapsed approval cannot authorise anything in the window
    between expiry and whenever a sweeper gets around to it.
    """
    if request.status is ApprovalStatus.PENDING and request.expires_at <= now:
        return ApprovalStatus.EXPIRED
    return request.status


def decide(
    session: Session,
    request: orm.ApprovalRequest,
    *,
    approved: bool,
    decided_by: str,
    occurred_at: datetime,
    note: str | None = None,
) -> orm.ApprovalRequest:
    """Approve or reject. Refuses self-approval and refuses to revive a lapsed request.

    Session 5 exposes no route to this function -- it exists so the rules can be tested
    now and so Session 6 wires a UI to something already proven, rather than proving it
    under deadline.
    """
    if request.requested_by == decided_by:
        raise SelfApprovalError(decided_by)

    if effective_status(request, now=occurred_at) is ApprovalStatus.EXPIRED:
        request.status = ApprovalStatus.EXPIRED
        session.flush()
        raise ApprovalExpiredError(request.id, request.expires_at)

    request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    request.decided_at = occurred_at
    request.decided_by = decided_by
    if note is not None:
        request.decision_note = note
    session.flush()
    return request


def expire_lapsed(session: Session, *, now: datetime) -> int:
    """Mark every lapsed pending request as expired. Returns the count.

    A convenience for a future scheduled job. Correctness does not depend on it ever
    running -- that is what `effective_status` is for.
    """
    lapsed = session.scalars(
        sa.select(orm.ApprovalRequest).where(
            orm.ApprovalRequest.status == ApprovalStatus.PENDING,
            orm.ApprovalRequest.expires_at <= now,
        )
    ).all()
    for request in lapsed:
        request.status = ApprovalStatus.EXPIRED
    session.flush()
    return len(lapsed)
