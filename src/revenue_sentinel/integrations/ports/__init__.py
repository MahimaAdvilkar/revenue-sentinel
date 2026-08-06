"""Port definitions -- the shape a real integration would have to take.

Six `Protocol` classes, one per external system. A real adapter is a sibling package
implementing the same protocol, with no call-site changes (ADR-0004 commitment 1).

Every method returns `JSONObject`: the payload the MCP tool wraps in its result
envelope. Ports return plain JSON rather than domain models on purpose -- an external
system returns JSON, and a port that returned `Opportunity` would be quietly asserting
that the remote system shares our domain model, which is the assumption that makes
integrations painful to replace.
"""

from __future__ import annotations

from revenue_sentinel.integrations.ports.crm import CrmPort
from revenue_sentinel.integrations.ports.engagement import EngagementPort
from revenue_sentinel.integrations.ports.enrichment import EnrichmentPort
from revenue_sentinel.integrations.ports.messaging import MessagingPort
from revenue_sentinel.integrations.ports.product import ProductPort
from revenue_sentinel.integrations.ports.support import SupportPort

__all__ = [
    "CrmPort",
    "EngagementPort",
    "EnrichmentPort",
    "MessagingPort",
    "ProductPort",
    "SupportPort",
]
