"""The approvals CLI, and the honesty it is required to print.

The interesting assertion here is not that approve works -- it is that the CLI says
`--as` is unverified. ADR-0018 makes that statement part of the product rather than a
footnote, so it is tested like any other output.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.cli import IDENTITY_WARNING
from revenue_sentinel.core.config import Settings
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.domain.enums import ApprovalStatus
from revenue_sentinel.governance import approval_service, approvals
from revenue_sentinel.orchestration import runner

APPROVER = "usr:revenue-lead"


def test_pending_requests_are_listed_with_a_typeable_reference(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> None:
    views = approval_service.list_requests(
        detected, now=settings.evaluation_timestamp, pending_only=True
    )

    assert len(views) == 1
    assert views[0].approval_ref.startswith("APR-")
    assert views[0].effective_status is ApprovalStatus.PENDING
    assert views[0].requested_by == "agent:policy_and_risk"
    assert views[0].intervention_title


def test_a_request_is_retrievable_by_its_reference(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> None:
    view = approval_service.list_requests(
        detected, now=settings.evaluation_timestamp, pending_only=True
    )[0]

    request = approval_service.get_by_ref(detected, view.approval_ref)
    assert request.approval_ref == view.approval_ref


def test_an_unknown_reference_is_a_clean_error_not_a_traceback(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    import pytest

    from revenue_sentinel.core.errors import NotFoundError

    with pytest.raises(NotFoundError, match="APR-404"):
        approval_service.get_by_ref(detected, "APR-404")


def test_a_lapsed_request_disappears_from_the_actionable_list(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> None:
    """Filtered on *effective* status, so a lapsed request is never offered for approval."""
    request = detected.scalar(
        sa.select(gov_orm.ApprovalRequest).where(
            gov_orm.ApprovalRequest.run_id == investigated.run_id
        )
    )
    assert request is not None
    after_expiry = request.expires_at

    assert approval_service.list_requests(detected, now=after_expiry, pending_only=True) == []
    everything = approval_service.list_requests(detected, now=after_expiry, pending_only=False)
    assert everything[0].effective_status is ApprovalStatus.EXPIRED


def test_approving_records_the_claimed_actor(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> None:
    view = approval_service.list_requests(
        detected, now=settings.evaluation_timestamp, pending_only=True
    )[0]

    decided = approval_service.decide(
        detected,
        approval_service.get_by_ref(detected, view.approval_ref),
        approved=True,
        decided_by=APPROVER,
        occurred_at=settings.evaluation_timestamp,
    )

    assert decided.status is ApprovalStatus.APPROVED
    assert decided.decided_by == APPROVER


def test_the_cli_states_that_the_identity_is_unverified() -> None:
    """ADR-0018. Understating this once would devalue every other honesty claim here."""
    assert "CLAIMED identity" in IDENTITY_WARNING
    assert "not an authenticated one" in IDENTITY_WARNING
    assert "no authentication" in IDENTITY_WARNING
    assert "impersonation" in IDENTITY_WARNING


def test_the_service_reuses_the_governance_rules_rather_than_reimplementing_them() -> None:
    """Two places that both know how to approve something is one too many."""
    assert approval_service.decide is approvals.decide
