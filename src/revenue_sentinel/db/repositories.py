"""Repositories -- the boundary between SQLAlchemy rows and domain models.

Everything above this module works with `domain/` Pydantic models and never sees an
ORM object. That keeps the layer boundary real: business logic cannot accidentally
depend on lazy loading, session identity, or a detached-instance error.

Only the tables Session 1 actually reads have repositories. The other nineteen
tables exist in the schema with no accessor yet, which is stated plainly in
`PROJECT_STATUS.md` rather than hidden behind speculative CRUD.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.errors import NotFoundError
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.domain.gtm import (
    Account,
    Activity,
    CompanyProfile,
    EngagementEvent,
    Opportunity,
    SupportIssue,
    UsageSnapshot,
)


class AccountRepository:
    """Read access to the account mirror."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_ref(self, account_ref: str) -> Account | None:
        row = self._session.scalar(
            sa.select(orm.Account).where(orm.Account.account_ref == account_ref)
        )
        return Account.model_validate(row) if row is not None else None

    def require_by_ref(self, account_ref: str) -> Account:
        account = self.get_by_ref(account_ref)
        if account is None:
            raise NotFoundError("account", account_ref)
        return account

    def get_by_id(self, account_id: UUID) -> Account | None:
        row = self._session.get(orm.Account, account_id)
        return Account.model_validate(row) if row is not None else None

    def list_all(self) -> list[Account]:
        rows = self._session.scalars(sa.select(orm.Account).order_by(orm.Account.account_ref)).all()
        return [Account.model_validate(row) for row in rows]

    def count(self) -> int:
        return self._session.scalar(sa.select(sa.func.count()).select_from(orm.Account)) or 0


class OpportunityRepository:
    """Read access to the opportunity mirror."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_ref(self, opportunity_ref: str) -> Opportunity | None:
        row = self._session.scalar(
            sa.select(orm.Opportunity).where(orm.Opportunity.opportunity_ref == opportunity_ref)
        )
        return Opportunity.model_validate(row) if row is not None else None

    def require_by_ref(self, opportunity_ref: str) -> Opportunity:
        opportunity = self.get_by_ref(opportunity_ref)
        if opportunity is None:
            raise NotFoundError("opportunity", opportunity_ref)
        return opportunity

    def get_by_id(self, opportunity_id: UUID) -> Opportunity | None:
        row = self._session.get(orm.Opportunity, opportunity_id)
        return Opportunity.model_validate(row) if row is not None else None

    def list_for_account(self, account_id: UUID) -> list[Opportunity]:
        rows = self._session.scalars(
            sa.select(orm.Opportunity)
            .where(orm.Opportunity.account_id == account_id)
            .order_by(orm.Opportunity.opportunity_ref)
        ).all()
        return [Opportunity.model_validate(row) for row in rows]

    def count(self) -> int:
        return self._session.scalar(sa.select(sa.func.count()).select_from(orm.Opportunity)) or 0


class ActivityRepository:
    """Read access to logged sales activity.

    `latest_for_opportunity` is what the Session 2 detector will use to compute days
    of sales silence -- hence the covering index on `(opportunity_id, occurred_at)`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_account(self, account_id: UUID) -> list[Activity]:
        rows = self._session.scalars(
            sa.select(orm.Activity)
            .where(orm.Activity.account_id == account_id)
            .order_by(orm.Activity.occurred_at.desc())
        ).all()
        return [Activity.model_validate(row) for row in rows]

    def latest_for_opportunity(self, opportunity_id: UUID) -> Activity | None:
        row = self._session.scalar(
            sa.select(orm.Activity)
            .where(orm.Activity.opportunity_id == opportunity_id)
            .order_by(orm.Activity.occurred_at.desc())
            .limit(1)
        )
        return Activity.model_validate(row) if row is not None else None

    def count(self) -> int:
        return self._session.scalar(sa.select(sa.func.count()).select_from(orm.Activity)) or 0


class UsageSnapshotRepository:
    """Read access to weekly product-usage rollups."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_account(self, account_id: UUID) -> list[UsageSnapshot]:
        rows = self._session.scalars(
            sa.select(orm.UsageSnapshot)
            .where(orm.UsageSnapshot.account_id == account_id)
            .order_by(orm.UsageSnapshot.period_start)
        ).all()
        return [UsageSnapshot.model_validate(row) for row in rows]

    def list_in_window(self, account_id: UUID, *, start: date, end: date) -> list[UsageSnapshot]:
        rows = self._session.scalars(
            sa.select(orm.UsageSnapshot)
            .where(
                orm.UsageSnapshot.account_id == account_id,
                orm.UsageSnapshot.period_start >= start,
                orm.UsageSnapshot.period_end <= end,
            )
            .order_by(orm.UsageSnapshot.period_start)
        ).all()
        return [UsageSnapshot.model_validate(row) for row in rows]

    def count(self) -> int:
        return self._session.scalar(sa.select(sa.func.count()).select_from(orm.UsageSnapshot)) or 0


class EngagementEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_account(self, account_id: UUID) -> list[EngagementEvent]:
        rows = self._session.scalars(
            sa.select(orm.EngagementEvent)
            .where(orm.EngagementEvent.account_id == account_id)
            .order_by(orm.EngagementEvent.occurred_at)
        ).all()
        return [EngagementEvent.model_validate(row) for row in rows]

    def count(self) -> int:
        return (
            self._session.scalar(sa.select(sa.func.count()).select_from(orm.EngagementEvent)) or 0
        )


class SupportIssueRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_account(self, account_id: UUID) -> list[SupportIssue]:
        rows = self._session.scalars(
            sa.select(orm.SupportIssue)
            .where(orm.SupportIssue.account_id == account_id)
            .order_by(orm.SupportIssue.opened_at)
        ).all()
        return [SupportIssue.model_validate(row) for row in rows]

    def count(self) -> int:
        return self._session.scalar(sa.select(sa.func.count()).select_from(orm.SupportIssue)) or 0


class CompanyProfileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_account(self, account_id: UUID) -> CompanyProfile | None:
        row = self._session.scalar(
            sa.select(orm.CompanyProfile).where(orm.CompanyProfile.account_id == account_id)
        )
        return CompanyProfile.model_validate(row) if row is not None else None

    def count(self) -> int:
        return self._session.scalar(sa.select(sa.func.count()).select_from(orm.CompanyProfile)) or 0
