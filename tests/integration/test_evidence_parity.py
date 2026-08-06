"""Evidence parity: MCP replaces the repository source without changing the evidence.

This is the test that makes Session 4's central claim checkable. If the transport
changes what the model sees, then "we swapped an implementation behind a port" is not
what happened -- the agent contract moved, and every recorded fixture silently became
a fixture for a different prompt.

`RepositoryEvidenceSource` is retained **only as the control for this test**. It is
legacy: its `get_email_activity` conflates meetings with email activity, where the MCP
contract separates the two into distinct tools. The MCP shape is the correct target.
That difference does not surface for `ACC-1001` (the account has no meetings), which is
why parity holds today -- but it is a real contract defect in the repository source and
is documented rather than papered over.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.agents.ports import EvidenceRecord, EvidenceSource
from revenue_sentinel.core.config import Settings
from revenue_sentinel.db.models import gtm as orm
from revenue_sentinel.domain.enums import SourceSystem
from revenue_sentinel.governance.stub import StubPolicyEngine
from revenue_sentinel.integrations.simulated.behaviour import SimulatedBehaviour
from revenue_sentinel.integrations.status import SIMULATED
from revenue_sentinel.mcp.client import InProcessMcpClient
from revenue_sentinel.mcp.context import ToolContext, build_simulated_adapters
from revenue_sentinel.orchestration.evidence_source import RepositoryEvidenceSource
from revenue_sentinel.orchestration.mcp_evidence_source import (
    EvidenceEnvelopeError,
    McpEvidenceSource,
)

EXPECTED_RECORDS = 6


@pytest.fixture
def repository_source(seeded_session: Session) -> RepositoryEvidenceSource:
    """The legacy control. Not used by the graph."""
    return RepositoryEvidenceSource(seeded_session)


@pytest.fixture
def mcp_source(seeded_session: Session, settings: Settings) -> Iterator[McpEvidenceSource]:
    context = ToolContext(
        session=seeded_session,
        adapters=build_simulated_adapters(seeded_session, SimulatedBehaviour()),
        occurred_at=settings.evaluation_timestamp,
        node_name="collect_evidence",
        policy=StubPolicyEngine(),
    )
    yield McpEvidenceSource(InProcessMcpClient(context), seeded_session)


def _refs(session: Session) -> tuple[orm.Account, orm.Opportunity]:
    account = session.scalar(sa.select(orm.Account).where(orm.Account.account_ref == "ACC-1001"))
    opportunity = session.scalar(
        sa.select(orm.Opportunity).where(orm.Opportunity.opportunity_ref == "OPP-2001")
    )
    assert account is not None
    assert opportunity is not None
    return account, opportunity


def _canonical(source: EvidenceSource, session: Session) -> list[dict[str, object]]:
    """The evidence exactly as the researcher would assemble it, in plan order."""
    account, opportunity = _refs(session)
    batches = (
        source.get_opportunity(opportunity.id),
        source.list_account_activities(account.id),
        source.get_usage_summary(account.id),
        source.get_email_activity(account.id),
        source.get_open_issues(account.id),
    )
    return [
        {"source": record.source_system.value, "tool": record.tool_name, "content": record.content}
        for batch in batches
        for record in batch
    ]


def _serialise(records: list[dict[str, object]]) -> str:
    return json.dumps(records, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# The claim
# ---------------------------------------------------------------------------
def test_both_sources_produce_byte_equivalent_canonical_evidence(
    repository_source: RepositoryEvidenceSource,
    mcp_source: McpEvidenceSource,
    seeded_session: Session,
) -> None:
    """Acceptance criterion 9, stated as strictly as it can be.

    Byte equivalence, not "close enough": the evidence text is hashed into the
    hypotheses prompt digest, so anything less would invalidate a recorded fixture.
    """
    via_repository = _canonical(repository_source, seeded_session)
    via_mcp = _canonical(mcp_source, seeded_session)

    assert _serialise(via_repository) == _serialise(via_mcp)


def test_both_sources_produce_the_same_number_of_records(
    repository_source: RepositoryEvidenceSource,
    mcp_source: McpEvidenceSource,
    seeded_session: Session,
) -> None:
    assert len(_canonical(repository_source, seeded_session)) == EXPECTED_RECORDS
    assert len(_canonical(mcp_source, seeded_session)) == EXPECTED_RECORDS


def test_ordering_and_source_labels_are_preserved(
    repository_source: RepositoryEvidenceSource,
    mcp_source: McpEvidenceSource,
    seeded_session: Session,
) -> None:
    """Ordering determines EV-001..EV-006, so a reordering renumbers every citation."""
    expected = [
        (SourceSystem.CRM.value, "crm_get_opportunity"),
        (SourceSystem.CRM.value, "crm_list_account_activities"),
        (SourceSystem.PRODUCT.value, "product_get_usage_summary"),
        (SourceSystem.PRODUCT.value, "product_get_usage_summary"),
        (SourceSystem.ENGAGEMENT.value, "engagement_get_email_activity"),
        (SourceSystem.SUPPORT.value, "support_get_open_issues"),
    ]
    for records in (
        _canonical(repository_source, seeded_session),
        _canonical(mcp_source, seeded_session),
    ):
        assert [(row["source"], row["tool"]) for row in records] == expected


def test_the_usage_summary_decomposes_into_one_record_per_period(
    mcp_source: McpEvidenceSource, seeded_session: Session
) -> None:
    """Two adjacent weeks are two citable facts, not one blob."""
    account, _ = _refs(seeded_session)
    records = mcp_source.get_usage_summary(account.id)

    assert len(records) == 2
    assert [record.content["feature_events"] for record in records] == [1250, 1750]
    assert records[1].content["week_over_week_growth"] == "0.4000"


# ---------------------------------------------------------------------------
# Transport metadata must not leak into the model's input
# ---------------------------------------------------------------------------
def test_no_transport_metadata_reaches_the_evidence_content(
    mcp_source: McpEvidenceSource, seeded_session: Session
) -> None:
    """Envelope fields are transport concerns and belong in `tool_calls`.

    Leaking them would change the prompt digest, meaning a transport change silently
    invalidated every recorded fixture.
    """
    leaked = {"ok", "integration_status", "tool", "error", "account_ref", "period_count"}

    for record in _canonical(mcp_source, seeded_session):
        content = record["content"]
        assert isinstance(content, dict)
        assert not (set(content) & leaked), f"{record['tool']} leaked {set(content) & leaked}"


def test_the_source_refuses_an_envelope_that_is_not_simulated(
    seeded_session: Session, settings: Settings
) -> None:
    """If a real adapter is ever bound, that must be a deliberate change here rather
    than a silent one downstream."""

    class NotSimulatedClient:
        def call_tool(self, tool_name: str, arguments: object) -> dict[str, object]:
            return {"tool": tool_name, "ok": True, "integration_status": "IMPLEMENTED", "data": {}}

        def list_tools(self) -> list[dict[str, object]]:
            return []

    account, _ = _refs(seeded_session)
    source = McpEvidenceSource(NotSimulatedClient(), seeded_session)  # type: ignore[arg-type]

    with pytest.raises(EvidenceEnvelopeError, match="SIMULATED"):
        source.get_open_issues(account.id)


def test_a_failed_tool_call_raises_rather_than_yielding_empty_evidence(
    seeded_session: Session, settings: Settings
) -> None:
    """Empty evidence would look like a finding. A failure must look like a failure."""

    class FailingClient:
        def call_tool(self, tool_name: str, arguments: object) -> dict[str, object]:
            return {
                "tool": tool_name,
                "ok": False,
                "integration_status": SIMULATED,
                "error": {"code": "ADAPTER_ERROR", "message": "boom"},
            }

        def list_tools(self) -> list[dict[str, object]]:
            return []

    account, _ = _refs(seeded_session)
    source = McpEvidenceSource(FailingClient(), seeded_session)  # type: ignore[arg-type]

    with pytest.raises(EvidenceEnvelopeError, match="ADAPTER_ERROR"):
        source.get_open_issues(account.id)


def test_the_mcp_source_satisfies_the_unchanged_agent_port(
    mcp_source: McpEvidenceSource,
) -> None:
    """The agent interface did not move. That is the whole claim."""
    assert isinstance(mcp_source, EvidenceSource)


def test_every_record_from_either_source_is_an_evidence_record(
    repository_source: RepositoryEvidenceSource,
    mcp_source: McpEvidenceSource,
    seeded_session: Session,
) -> None:
    account, opportunity = _refs(seeded_session)
    for source in (repository_source, mcp_source):
        for record in source.get_opportunity(opportunity.id):
            assert isinstance(record, EvidenceRecord)
        for record in source.get_open_issues(account.id):
            assert isinstance(record, EvidenceRecord)
