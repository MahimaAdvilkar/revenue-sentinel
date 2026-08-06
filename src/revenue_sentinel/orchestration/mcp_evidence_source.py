"""`McpEvidenceSource` -- evidence gathered through the GTM MCP server.

Implements the **unchanged** `agents/ports.py:EvidenceSource` protocol. The Research
Agent, the planner, the schemas, and the graph are untouched: Session 4 swaps an
implementation behind a port, which is the whole claim ADR-0004 commitment 1 makes.

## Why this maps rather than forwards

Raw MCP envelopes never reach a prompt. An envelope carries transport concerns --
`tool`, `ok`, `integration_status` -- and a `data` payload that includes routing keys
(`account_ref`, `count`, `period_count`) the model has no use for. Passing those
through would put transport metadata into the evidence text and change the prompt
digest, which would mean a transport change silently invalidated recorded fixtures.

So this class validates the envelope, asserts the integration status, extracts the
typed business payload, and maps it into the **canonical** evidence shape that
`RepositoryEvidenceSource` established. Transport and tool-call metadata live in
`tool_calls` and the observability records, where they belong.

A parity test asserts byte-equivalence of the canonical evidence produced by both
sources for INC-001.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from revenue_sentinel.agents.ports import EvidenceRecord
from revenue_sentinel.core.errors import NotFoundError, RevenueSentinelError
from revenue_sentinel.core.types import JSONObject, JSONValue
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.domain.enums import SourceSystem
from revenue_sentinel.integrations.status import SIMULATED
from revenue_sentinel.mcp.client import McpClient

# The repository source applied no time or period bound. These sentinels reproduce
# that through tools whose schemas require an explicit window.
BEGINNING_OF_TIME: Final = datetime(1970, 1, 1, tzinfo=UTC)
EARLIEST_PERIOD: Final = date(1970, 1, 1)
LATEST_PERIOD: Final = date(2999, 12, 31)
DEFAULT_ACTIVITY_LIMIT: Final = 10


class EvidenceEnvelopeError(RevenueSentinelError):
    """A tool result was not a usable evidence envelope."""


class McpEvidenceSource:
    """Evidence via MCP, mapped to the canonical shape."""

    def __init__(self, client: McpClient, session: Session) -> None:
        self._client = client
        # Business references are what the tools take; the port speaks in UUIDs.
        # Resolution is a lookup, never part of the evidence content.
        self._session = session

    # -- envelope handling ---------------------------------------------------
    def _payload(self, tool_name: str, arguments: JSONObject) -> JSONObject:
        """Call a tool and return its business payload, or raise.

        Validates the envelope shape and asserts `SIMULATED` -- if a real adapter is
        ever bound, that assertion is the thing that has to be revisited deliberately
        rather than a silent behaviour change.
        """
        envelope = self._client.call_tool(tool_name, arguments)

        if not isinstance(envelope, dict) or "ok" not in envelope:
            raise EvidenceEnvelopeError(f"{tool_name} returned a malformed envelope")

        if envelope.get("integration_status") != SIMULATED:
            raise EvidenceEnvelopeError(
                f"{tool_name} reported integration_status="
                f"{envelope.get('integration_status')!r}; v1 expects SIMULATED"
            )

        if not envelope["ok"]:
            error = envelope.get("error", {})
            code = error.get("code") if isinstance(error, dict) else None
            raise EvidenceEnvelopeError(f"{tool_name} failed: {code}")

        data = envelope.get("data")
        if not isinstance(data, dict):
            raise EvidenceEnvelopeError(f"{tool_name} returned no data payload")
        return data

    def _account_ref(self, account_id: UUID) -> str:
        row = self._session.get(orm.Account, account_id)
        if row is None:
            raise NotFoundError("account", str(account_id))
        return row.account_ref

    def _opportunity_ref(self, opportunity_id: UUID) -> str:
        row = self._session.get(orm.Opportunity, opportunity_id)
        if row is None:
            raise NotFoundError("opportunity", str(opportunity_id))
        return row.opportunity_ref

    # -- the port ------------------------------------------------------------
    def get_opportunity(self, opportunity_id: UUID) -> tuple[EvidenceRecord, ...]:
        data = self._payload(
            "crm_get_opportunity",
            {"opportunity_ref": self._opportunity_ref(opportunity_id)},
        )
        # `account_ref` is a routing key, not evidence. Dropped so the canonical
        # content matches what the repository source produced.
        content: JSONObject = {
            key: data[key]
            for key in (
                "opportunity_ref",
                "name",
                "account",
                "stage",
                "amount",
                "currency",
                "probability",
                "expected_close_date",
                "owner_id",
                "is_simulated",
            )
        }
        return (
            EvidenceRecord(
                source_system=SourceSystem.CRM,
                tool_name="crm_get_opportunity",
                content=content,
            ),
        )

    def list_account_activities(
        self, account_id: UUID, *, limit: int = DEFAULT_ACTIVITY_LIMIT
    ) -> tuple[EvidenceRecord, ...]:
        data = self._payload(
            "crm_list_account_activities",
            {
                "account_ref": self._account_ref(account_id),
                "since": BEGINNING_OF_TIME.isoformat(),
                "limit": limit,
            },
        )
        return (
            EvidenceRecord(
                source_system=SourceSystem.CRM,
                tool_name="crm_list_account_activities",
                content={
                    "count": data["count"],
                    "most_recent_first": data["most_recent_first"],
                },
            ),
        )

    def get_usage_summary(self, account_id: UUID) -> tuple[EvidenceRecord, ...]:
        """One record per weekly period, matching the canonical decomposition."""
        data = self._payload(
            "product_get_usage_summary",
            {
                "account_ref": self._account_ref(account_id),
                "period_start": EARLIEST_PERIOD.isoformat(),
                "period_end": LATEST_PERIOD.isoformat(),
            },
        )
        periods = data["periods"]
        if not isinstance(periods, list):
            raise EvidenceEnvelopeError("product_get_usage_summary returned no periods")

        records: list[EvidenceRecord] = []
        for period in periods:
            if not isinstance(period, dict):
                raise EvidenceEnvelopeError("malformed usage period")
            records.append(
                EvidenceRecord(
                    source_system=SourceSystem.PRODUCT,
                    tool_name="product_get_usage_summary",
                    content=dict(period),
                )
            )
        return tuple(records)

    def get_email_activity(self, account_id: UUID) -> tuple[EvidenceRecord, ...]:
        data = self._payload(
            "engagement_get_email_activity",
            {
                "account_ref": self._account_ref(account_id),
                "since": BEGINNING_OF_TIME.isoformat(),
            },
        )
        totals = data["totals_by_event_type"]
        meetings: JSONValue = 0
        if isinstance(totals, dict):
            meetings = totals.get("meeting_held", 0)
        return (
            EvidenceRecord(
                source_system=SourceSystem.ENGAGEMENT,
                tool_name="engagement_get_email_activity",
                content={
                    "totals_by_event_type": totals,
                    "meetings_held": meetings,
                    "events": data["events"],
                },
            ),
        )

    def get_open_issues(self, account_id: UUID) -> tuple[EvidenceRecord, ...]:
        data = self._payload(
            "support_get_open_issues", {"account_ref": self._account_ref(account_id)}
        )
        return (
            EvidenceRecord(
                source_system=SourceSystem.SUPPORT,
                tool_name="support_get_open_issues",
                content={"open_count": data["open_count"], "issues": data["issues"]},
            ),
        )
