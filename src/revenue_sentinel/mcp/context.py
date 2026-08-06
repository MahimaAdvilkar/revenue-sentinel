"""What a tool invocation has access to.

Assembled once per run and passed to every handler. Adapters are constructed here so a
handler never chooses its own -- which is what makes swapping the simulated bundle for
a real one a single-site change (ADR-0004 commitment 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import ModuleType
from uuid import UUID

from sqlalchemy.orm import Session

from revenue_sentinel.integrations.ports import (
    CrmPort,
    EngagementPort,
    EnrichmentPort,
    MessagingPort,
    ProductPort,
    SupportPort,
)
from revenue_sentinel.integrations.simulated import (
    crm as crm_module,
)
from revenue_sentinel.integrations.simulated import (
    engagement as engagement_module,
)
from revenue_sentinel.integrations.simulated import (
    enrichment as enrichment_module,
)
from revenue_sentinel.integrations.simulated import (
    messaging as messaging_module,
)
from revenue_sentinel.integrations.simulated import (
    product as product_module,
)
from revenue_sentinel.integrations.simulated import (
    support as support_module,
)
from revenue_sentinel.integrations.simulated.behaviour import SimulatedBehaviour
from revenue_sentinel.mcp.gate import PolicyEngine


@dataclass(frozen=True, slots=True)
class AdapterBundle:
    """The bound adapters, plus the module each came from.

    The module is kept so `INTEGRATION_STATUS` can be read from the code that actually
    serves the request rather than from a constant chosen at the call site.
    """

    crm: CrmPort
    product: ProductPort
    engagement: EngagementPort
    support: SupportPort
    enrichment: EnrichmentPort
    messaging: MessagingPort

    modules: dict[str, ModuleType] = field(
        default_factory=lambda: {
            "crm": crm_module,
            "product": product_module,
            "engagement": engagement_module,
            "support": support_module,
            "enrichment": enrichment_module,
            "messaging": messaging_module,
        }
    )


def build_simulated_adapters(session: Session, behaviour: SimulatedBehaviour) -> AdapterBundle:
    """Every adapter in the bundle is SIMULATED (ADR-0004)."""
    return AdapterBundle(
        crm=crm_module.SimulatedCrmAdapter(session, behaviour),
        product=product_module.SimulatedProductAdapter(session, behaviour),
        engagement=engagement_module.SimulatedEngagementAdapter(session, behaviour),
        support=support_module.SimulatedSupportAdapter(session, behaviour),
        enrichment=enrichment_module.SimulatedEnrichmentAdapter(session, behaviour),
        messaging=messaging_module.SimulatedMessagingAdapter(behaviour),
    )


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything a tool call may reach."""

    session: Session
    adapters: AdapterBundle
    occurred_at: datetime
    node_name: str
    run_id: UUID | None = None
    policy: PolicyEngine | None = None
