"""Integration status -- the honesty boundary, as data.

Every adapter module declares `INTEGRATION_STATUS`. The MCP server reads it **from
the bound adapter** and stamps it on every tool result, so the badge a dashboard
renders is derived from the code that actually served the request rather than from a
constant somewhere convenient (ADR-0004 commitment 2).

There is no configuration that makes a simulated adapter claim to be real. The only
way `INTEGRATION_STATUS` becomes `"IMPLEMENTED"` is for a real adapter module to exist
and be bound.
"""

from __future__ import annotations

from types import ModuleType
from typing import Final, Literal

IntegrationStatus = Literal["SIMULATED", "IMPLEMENTED"]

SIMULATED: Final[IntegrationStatus] = "SIMULATED"
IMPLEMENTED: Final[IntegrationStatus] = "IMPLEMENTED"

STATUS_ATTRIBUTE: Final = "INTEGRATION_STATUS"


class MissingIntegrationStatusError(RuntimeError):
    """An adapter module did not declare its status.

    Fatal rather than defaulted. Defaulting to `SIMULATED` would be safe today and
    catastrophic the day a real adapter forgets the declaration and is silently
    labelled simulated -- or the reverse.
    """


def status_of(adapter_module: ModuleType) -> IntegrationStatus:
    """Read `INTEGRATION_STATUS` from the module that will serve the request."""
    status = getattr(adapter_module, STATUS_ATTRIBUTE, None)
    if status == SIMULATED:
        return SIMULATED
    if status == IMPLEMENTED:
        return IMPLEMENTED
    raise MissingIntegrationStatusError(
        f"{adapter_module.__name__} must declare "
        f'{STATUS_ATTRIBUTE} = "SIMULATED" or "IMPLEMENTED"; got {status!r}'
    )
