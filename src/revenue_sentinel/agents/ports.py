"""The evidence port.

`agents/` may not import `db/` (boundary R5), so an agent never queries anything. It
receives an `EvidenceSource` and calls it. In Session 3 the implementation is
repository-backed and lives in `orchestration/`; in Session 4 it becomes MCP-backed
and the agents do not change.

**The method names are deliberately the names of the MCP tools that replace them.**
`get_opportunity` here becomes `crm_get_opportunity` there, with the same arguments
and the same returned shape. That is what makes Session 4 a swap behind the port
rather than a redesign of the agent -- and it is why the allowlist in
`intelligence/schemas.py` already uses the MCP names.

Every method returns a **tuple** of `EvidenceRecord`, because one call can yield
several distinct facts: two weekly usage periods are two pieces of evidence a
hypothesis may cite separately, not one blob. In Session 4 the MCP tool returns a
single payload and the adapter decomposes it the same way.

`content` is untrusted (rule 14). The source labels it; nothing downstream un-labels
it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.enums import SourceSystem


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One retrieved fact, before it becomes a persisted `EvidenceItem`.

    Carries no id: references (`EV-001`, `EV-002`, ...) are assigned in retrieval
    order by the researcher, so they are stable for a given plan and a given source
    ordering rather than dependent on insertion timing.
    """

    source_system: SourceSystem
    tool_name: str
    content: JSONObject


@runtime_checkable
class EvidenceSource(Protocol):
    """Read-only access to GTM records, one method per future MCP tool."""

    def get_opportunity(self, opportunity_id: UUID) -> tuple[EvidenceRecord, ...]: ...

    def list_account_activities(
        self, account_id: UUID, *, limit: int = 10
    ) -> tuple[EvidenceRecord, ...]: ...

    def get_usage_summary(self, account_id: UUID) -> tuple[EvidenceRecord, ...]: ...

    def get_email_activity(self, account_id: UUID) -> tuple[EvidenceRecord, ...]: ...

    def get_open_issues(self, account_id: UUID) -> tuple[EvidenceRecord, ...]: ...
