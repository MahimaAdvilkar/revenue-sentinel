"""Support adapter -- **SIMULATED**.

Reads the locally seeded `support_issues` mirror. No ticketing system is contacted.

## What changes when this becomes real

**API.** Zendesk Ticketing (`/api/v2/search.json?query=type:ticket status<solved`) or
Intercom Conversations (`/conversations/search`). Both search rather than filter, so
"open issues for this account" becomes a query-language string whose semantics differ
between them.

**Auth.** Zendesk: API token or OAuth against a subdomain. Intercom: an access token
per workspace. Both are per-tenant and neither maps cleanly to a single env var once
more than one customer exists.

**Rate limits.** Zendesk: 700 requests/minute on Enterprise, far lower on lower tiers,
with `429` and `Retry-After`. Search endpoints are metered more tightly than reads and
cap total results at 1,000 -- so an account with a long history cannot be fully
enumerated by this call at all.

**Pagination.** Cursor-based; Zendesk deprecated offset pagination beyond 10,000
results. Our unbounded "all open issues" becomes a paged loop with a ceiling.

**Fields that differ.** Severity is a per-tenant custom field, not a P1-P4 enum --
the mapping is configuration, not code. `status` has more states than ours (`new`,
`hold`, `pending`) and the open/closed split is a business decision. Ticket bodies
contain customer PII and attachments, neither of which our fixture models, and both of
which change what may be sent to a model.
"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.domain.enums import SupportStatus
from revenue_sentinel.integrations.simulated.behaviour import SimulatedBehaviour
from revenue_sentinel.integrations.status import SIMULATED

INTEGRATION_STATUS: Final = SIMULATED

OPEN_STATUSES: Final = (SupportStatus.OPEN, SupportStatus.PENDING)


class SimulatedSupportAdapter:
    """Fixture-backed support."""

    def __init__(self, session: Session, behaviour: SimulatedBehaviour) -> None:
        self._session = session
        self._behaviour = behaviour

    def get_open_issues(self, *, account_ref: str) -> JSONObject:
        self._behaviour.before_call("support_get_open_issues")
        account = self._session.scalar(
            sa.select(orm.Account).where(orm.Account.account_ref == account_ref)
        )
        if account is None:
            return {}
        rows = self._session.scalars(
            sa.select(orm.SupportIssue)
            .where(
                orm.SupportIssue.account_id == account.id,
                orm.SupportIssue.status.in_(list(OPEN_STATUSES)),
            )
            .order_by(orm.SupportIssue.opened_at)
        ).all()
        return {
            "account_ref": account_ref,
            "open_count": len(rows),
            "issues": [
                {
                    "external_ref": row.external_ref,
                    "severity": row.severity.value,
                    "status": row.status.value,
                    "opened_at": row.opened_at.isoformat(),
                    # Untrusted free text, carried verbatim (rule 14).
                    "summary": row.summary,
                }
                for row in rows
            ],
        }
