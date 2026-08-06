"""Fixture-backed adapters -- every one of them SIMULATED (ADR-0004).

Each module declares `INTEGRATION_STATUS = "SIMULATED"` and carries a
"What changes when this becomes real" section naming the specific API, auth model,
rate limits, pagination, and the fields that would differ. Both are asserted by test:
the constant because the MCP server reads it to stamp every result, and the section
because it is what turns simulation from an excuse into a design artifact.

A real adapter would be a sibling package implementing the same port. No call site
changes.
"""

from __future__ import annotations

from revenue_sentinel.integrations.simulated.crm import SimulatedCrmAdapter
from revenue_sentinel.integrations.simulated.engagement import SimulatedEngagementAdapter
from revenue_sentinel.integrations.simulated.enrichment import SimulatedEnrichmentAdapter
from revenue_sentinel.integrations.simulated.messaging import SimulatedMessagingAdapter
from revenue_sentinel.integrations.simulated.product import SimulatedProductAdapter
from revenue_sentinel.integrations.simulated.support import SimulatedSupportAdapter

__all__ = [
    "SimulatedCrmAdapter",
    "SimulatedEngagementAdapter",
    "SimulatedEnrichmentAdapter",
    "SimulatedMessagingAdapter",
    "SimulatedProductAdapter",
    "SimulatedSupportAdapter",
]
