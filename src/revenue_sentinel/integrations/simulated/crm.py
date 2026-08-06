"""CRM adapter -- **SIMULATED**.

Reads and writes the locally seeded GTM mirror. No external system is contacted.

## What changes when this becomes real

**API.** HubSpot CRM v3 (`/crm/v3/objects/companies`, `/deals`, `/engagements`) or
Salesforce REST v60 (`/services/data/v60.0/sobjects/Account`, `/Opportunity`, `/Task`).
Both model an "opportunity" as a Deal on a pipeline stage, so `stage` becomes a
pipeline-scoped id rather than our enum and needs a mapping table per tenant.

**Auth.** OAuth 2.0 authorisation-code flow with refresh tokens, per connected
portal -- not an API key. Tokens are per-tenant, expire, and must be stored encrypted
and rotated. `Settings` grows `HUBSPOT_CLIENT_ID` / `_SECRET` and a token store; none
of that exists today.

**Rate limits.** HubSpot: 100 requests / 10s per portal, 250k/day; Salesforce: a
24-hour rolling org limit. Both return `429` with `Retry-After`, which is what
`RATE_LIMITED` exists to represent. The current adapter never throttles, so the retry
path is exercised only by scripted injection.

**Pagination.** Both cursor-paginate (`after` / `nextRecordsUrl`). Our `limit` becomes
a page size plus a cursor loop, and `list_account_activities` becomes the first place
that matters -- an active account has thousands of engagements.

**Fields that differ.** `amount` arrives as a string in HubSpot and a float in
Salesforce; both need parsing to `Decimal` at the boundary, not after. `probability` is
derived from stage in Salesforce rather than stored. Custom fields are portal-specific
and arrive under opaque internal names. Deleted records are soft-deleted and still
returned unless filtered.

**Writes.** `create_task` becomes a real Task/Engagement object with an owner id we do
not currently map. `update_opportunity` becomes a PATCH that can fail on validation
rules, workflow triggers, and field-level security -- none of which the simulated
version can fail on.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.integrations.simulated.behaviour import SimulatedBehaviour
from revenue_sentinel.integrations.status import SIMULATED

INTEGRATION_STATUS: Final = SIMULATED


class SimulatedCrmAdapter:
    """Fixture-backed CRM. Writes land in memory, not in the mirror tables.

    Write results are recorded but not persisted to `accounts` / `opportunities`:
    Session 4 has no execution layer, and a write that silently mutated the seed would
    make the demo non-reproducible on the second run.
    """

    def __init__(self, session: Session, behaviour: SimulatedBehaviour) -> None:
        self._session = session
        self._behaviour = behaviour

    # -- reads ---------------------------------------------------------------
    def search_accounts(self, *, query: str, segment: str | None, limit: int) -> JSONObject:
        self._behaviour.before_call("crm_search_accounts")
        statement = sa.select(orm.Account).where(orm.Account.name.ilike(f"%{query}%"))
        if segment is not None:
            statement = statement.where(orm.Account.segment == segment)
        rows = self._session.scalars(statement.order_by(orm.Account.account_ref).limit(limit)).all()
        return {
            "count": len(rows),
            "accounts": [
                {
                    "account_ref": row.account_ref,
                    "name": row.name,
                    "segment": row.segment.value,
                    "industry": row.industry,
                    "is_simulated": row.is_simulated,
                }
                for row in rows
            ],
        }

    def get_account(self, *, account_ref: str) -> JSONObject:
        self._behaviour.before_call("crm_get_account")
        row = self._session.scalar(
            sa.select(orm.Account).where(orm.Account.account_ref == account_ref)
        )
        if row is None:
            return {}
        return {
            "account_ref": row.account_ref,
            "name": row.name,
            "segment": row.segment.value,
            "industry": row.industry,
            "employee_count": row.employee_count,
            "owner_id": row.owner_id,
            "is_simulated": row.is_simulated,
        }

    def get_opportunity(self, *, opportunity_ref: str) -> JSONObject:
        self._behaviour.before_call("crm_get_opportunity")
        row = self._session.scalar(
            sa.select(orm.Opportunity).where(orm.Opportunity.opportunity_ref == opportunity_ref)
        )
        if row is None:
            return {}
        account = self._session.get(orm.Account, row.account_id)
        return {
            "opportunity_ref": row.opportunity_ref,
            "name": row.name,
            "account_ref": account.account_ref if account else None,
            "account": account.name if account else None,
            "stage": row.stage.value,
            "amount": str(row.amount),
            "currency": row.currency,
            "probability": str(row.probability),
            "expected_close_date": row.expected_close_date.isoformat(),
            "owner_id": row.owner_id,
            "is_simulated": row.is_simulated,
        }

    def list_account_activities(
        self, *, account_ref: str, since: datetime, limit: int
    ) -> JSONObject:
        self._behaviour.before_call("crm_list_account_activities")
        account = self._session.scalar(
            sa.select(orm.Account).where(orm.Account.account_ref == account_ref)
        )
        if account is None:
            return {}
        rows = self._session.scalars(
            sa.select(orm.Activity)
            .where(orm.Activity.account_id == account.id, orm.Activity.occurred_at >= since)
            .order_by(orm.Activity.occurred_at.desc())
            .limit(limit)
        ).all()
        return {
            "account_ref": account_ref,
            "count": len(rows),
            "most_recent_first": [
                {
                    "type": row.activity_type.value,
                    "direction": row.direction.value,
                    "occurred_at": row.occurred_at.isoformat(),
                    # Untrusted free text, carried verbatim (rule 14).
                    "subject": row.subject,
                    "body": row.body,
                }
                for row in rows
            ],
        }

    # -- writes --------------------------------------------------------------
    def create_task(
        self,
        *,
        opportunity_ref: str,
        title: str,
        description: str,
        due_date: date,
        assignee_ref: str,
    ) -> JSONObject:
        self._behaviour.before_call("crm_create_task")
        return {
            "task_ref": f"TSK-{uuid4().hex[:8].upper()}",
            "opportunity_ref": opportunity_ref,
            "title": title,
            "description": description,
            "due_date": due_date.isoformat(),
            "assignee_ref": assignee_ref,
            "created": True,
        }

    def update_opportunity(
        self, *, opportunity_ref: str, field_name: str, value: str, reason: str
    ) -> JSONObject:
        self._behaviour.before_call("crm_update_opportunity")
        return {
            "opportunity_ref": opportunity_ref,
            "field": field_name,
            "new_value": value,
            "reason": reason,
            "updated": True,
        }
