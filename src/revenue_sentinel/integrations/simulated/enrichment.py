"""Enrichment adapter -- **SIMULATED**.

Reads the locally seeded `company_profiles` mirror. No provider is contacted.

## What changes when this becomes real

**API.** Clearbit Enrichment (`/v2/companies/find?domain=`) or Apollo
(`/v1/organizations/enrich`). Both key on **domain**, not on our `account_ref`, so the
first real change is that this call needs a domain we do not currently store.

**Auth.** A single API key per account -- the simplest auth in the system, which is why
ADR-0004 names enrichment as the first realistic candidate for a genuine integration.

**Rate limits.** Clearbit: plan-dependent, commonly 600/minute, with a `202` meaning
"looking it up, ask again" -- an async pattern our synchronous port has no way to
express. Handling it needs either polling or a webhook, and that changes the port
signature.

**Pagination.** None; single-record lookups.

**Cost.** This is the integration that bills per lookup, which is why
`enrichment_cost_anomaly` is a ROADMAP detector. A retry loop here spends real money,
so caching and a per-period budget become correctness concerns rather than
optimisations.

**Fields that differ.** Coverage is partial and uneven -- roughly 60-80% of B2B domains
resolve, and small or non-US companies resolve worst. `tech_stack` is inferred from
crawled markup and is frequently stale or wrong. A real adapter must distinguish
"not found", "found with no tech data", and "provider unavailable"; our fixture returns
one shape for all three.
"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.integrations.simulated.behaviour import SimulatedBehaviour
from revenue_sentinel.integrations.status import SIMULATED

INTEGRATION_STATUS: Final = SIMULATED


class SimulatedEnrichmentAdapter:
    """Fixture-backed enrichment."""

    def __init__(self, session: Session, behaviour: SimulatedBehaviour) -> None:
        self._session = session
        self._behaviour = behaviour

    def get_company_profile(self, *, account_ref: str) -> JSONObject:
        self._behaviour.before_call("enrichment_get_company_profile")
        account = self._session.scalar(
            sa.select(orm.Account).where(orm.Account.account_ref == account_ref)
        )
        if account is None:
            return {}
        row = self._session.scalar(
            sa.select(orm.CompanyProfile).where(orm.CompanyProfile.account_id == account.id)
        )
        if row is None:
            return {}
        return {
            "account_ref": account_ref,
            "hq_country": row.hq_country,
            "revenue_band": row.revenue_band,
            "tech_stack": row.tech_stack,
            "enriched_at": row.enriched_at.isoformat(),
            "source": row.source,
            "is_simulated": row.is_simulated,
        }
