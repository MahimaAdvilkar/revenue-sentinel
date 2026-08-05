"""Agents as pure functions, and nodes as thin ones.

ADR-0002 rule 3 says the entire agent layer must be testable without LangGraph
running at all. This file is the evidence: every agent and every node is exercised
here with a stub client, an in-memory evidence source, no graph, and no database.

`test_node_bodies_stay_thin` is the guard against absorption -- the failure mode
ADR-0002 was written to prevent. A fat node is its leading indicator.
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from revenue_sentinel.agents import analyst, planner, researcher
from revenue_sentinel.agents.ports import EvidenceRecord
from revenue_sentinel.core.config import PROJECT_ROOT
from revenue_sentinel.core.errors import FabricatedCitationError, StructuredOutputError
from revenue_sentinel.domain.enums import (
    AccountSegment,
    IncidentStatus,
    IncidentType,
    OpportunityStage,
    Severity,
    SourceSystem,
)
from revenue_sentinel.domain.gtm import Account, Opportunity
from revenue_sentinel.domain.incidents import Incident
from revenue_sentinel.intelligence.schemas import (
    EvidenceRequest,
    EvidenceSelection,
    EvidenceSourceName,
    HypothesisDraft,
    HypothesisSet,
    InvestigationPlan,
    PlanStep,
)
from revenue_sentinel.orchestration import nodes
from revenue_sentinel.orchestration.state import WorkflowState

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel

    from revenue_sentinel.intelligence.ports import LLMClient

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
MAX_NODE_STATEMENTS = 6


class InMemoryEvidenceSource:
    """Records what was asked for, returns fixed content. No database."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _record(self, tool: str, system: SourceSystem) -> tuple[EvidenceRecord, ...]:
        self.calls.append(tool)
        return (EvidenceRecord(source_system=system, tool_name=tool, content={"tool": tool}),)

    def get_opportunity(self, opportunity_id: UUID) -> tuple[EvidenceRecord, ...]:
        return self._record("crm_get_opportunity", SourceSystem.CRM)

    def list_account_activities(
        self, account_id: UUID, *, limit: int = 10
    ) -> tuple[EvidenceRecord, ...]:
        return self._record("crm_list_account_activities", SourceSystem.CRM)

    def get_usage_summary(self, account_id: UUID) -> tuple[EvidenceRecord, ...]:
        """Two records, as the real source does for two weekly periods."""
        self.calls.append("product_get_usage_summary")
        return tuple(
            EvidenceRecord(
                source_system=SourceSystem.PRODUCT,
                tool_name="product_get_usage_summary",
                content={"period": index},
            )
            for index in range(2)
        )

    def get_email_activity(self, account_id: UUID) -> tuple[EvidenceRecord, ...]:
        return self._record("engagement_get_email_activity", SourceSystem.ENGAGEMENT)

    def get_open_issues(self, account_id: UUID) -> tuple[EvidenceRecord, ...]:
        return self._record("support_get_open_issues", SourceSystem.SUPPORT)


def an_account() -> Account:
    return Account(
        id=uuid4(),
        account_ref="ACC-1001",
        name="Northwind Logistics",
        segment=AccountSegment.MID_MARKET,
        industry="Transportation & Logistics",
        employee_count=850,
        owner_id="USR-77",
        created_at=NOW,
        updated_at=NOW,
    )


def an_opportunity() -> Opportunity:
    return Opportunity(
        id=uuid4(),
        opportunity_ref="OPP-2001",
        account_id=uuid4(),
        name="Northwind Logistics - Platform Expansion",
        stage=OpportunityStage.PROPOSAL,
        amount=Decimal("180000.00"),
        currency="USD",
        expected_close_date=date(2026, 9, 15),
        probability=Decimal("0.6000"),
        owner_id="USR-77",
        created_at=NOW,
        updated_at=NOW,
    )


def an_incident() -> Incident:
    return Incident(
        id=uuid4(),
        incident_ref="INC-001",
        signal_id=uuid4(),
        incident_type=IncidentType.STALLED_OPPORTUNITY,
        status=IncidentStatus.TRIAGED,
        severity=Severity.HIGH,
        account_id=uuid4(),
        opened_at=NOW,
        title="stalled",
    )


def a_plan() -> InvestigationPlan:
    return InvestigationPlan(
        steps=(
            PlanStep(order=1, source=EvidenceSourceName.CRM_ACTIVITIES, objective="history"),
            PlanStep(order=2, source=EvidenceSourceName.PRODUCT_USAGE, objective="trend"),
        ),
        rationale="two halves of the contradiction",
    )


def a_hypothesis_set() -> HypothesisSet:
    return HypothesisSet(
        hypotheses=(
            HypothesisDraft(rank=1, statement="one", confidence=Decimal("0.7"), cites=("EV-001",)),
            HypothesisDraft(rank=2, statement="two", confidence=Decimal("0.4"), cites=("EV-002",)),
        )
    )


def a_state(**overrides: object) -> WorkflowState:
    defaults: dict[str, object] = {
        "run_id": uuid4(),
        "incident_id": uuid4(),
        "incident": an_incident(),
        "account": an_account(),
        "opportunity": an_opportunity(),
        "evaluated_at": NOW,
        "days_inactive": 14,
        "usage_growth": "0.4000",
    }
    defaults.update(overrides)
    return WorkflowState(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------
def test_the_planner_returns_the_plan_and_its_model_call(
    make_stub_llm: Callable[[dict[str, BaseModel]], LLMClient],
) -> None:
    """The response, not just the output -- an agent that discarded the metadata
    would make the cost ledger impossible to build."""
    llm = make_stub_llm({planner.NODE_NAME: a_plan()})

    response = planner.plan_investigation(
        planner.PlanningInput(
            incident=an_incident(),
            account=an_account(),
            opportunity=an_opportunity(),
            days_inactive=14,
            usage_growth=Decimal("0.40"),
        ),
        llm=llm,
        model_id="claude-opus-5",
        effort="high",
    )

    assert response.output == a_plan()
    assert response.model_id == "claude-opus-5"


# ---------------------------------------------------------------------------
# Researcher
# ---------------------------------------------------------------------------
def test_a_selection_within_the_plan_is_accepted(
    make_stub_llm: Callable[[dict[str, BaseModel]], LLMClient],
) -> None:
    selection = EvidenceSelection(
        requests=(EvidenceRequest(source=EvidenceSourceName.PRODUCT_USAGE, reason="trend"),)
    )
    llm = make_stub_llm({researcher.NODE_NAME: selection})

    response = researcher.select_sources(a_plan(), llm=llm, model_id="claude-opus-5", effort="high")
    assert response.output == selection


def test_a_selection_outside_the_plan_is_refused(
    make_stub_llm: Callable[[dict[str, BaseModel]], LLMClient],
) -> None:
    """Injection defence layer 4, at the agent boundary."""
    selection = EvidenceSelection(
        requests=(EvidenceRequest(source=EvidenceSourceName.SUPPORT, reason="not planned"),)
    )
    llm = make_stub_llm({researcher.NODE_NAME: selection})

    with pytest.raises(StructuredOutputError, match="outside the plan"):
        researcher.select_sources(a_plan(), llm=llm, model_id="claude-opus-5", effort="high")


def test_gathering_assigns_contiguous_references_across_a_multi_record_source() -> None:
    """Usage yields two records; references must stay contiguous across the flatten."""
    selection = EvidenceSelection(
        requests=(
            EvidenceRequest(source=EvidenceSourceName.CRM_ACTIVITIES, reason="history"),
            EvidenceRequest(source=EvidenceSourceName.PRODUCT_USAGE, reason="trend"),
            EvidenceRequest(source=EvidenceSourceName.SUPPORT, reason="friction"),
        )
    )
    source = InMemoryEvidenceSource()

    gathered = researcher.gather(
        selection, source=source, account_id=uuid4(), opportunity_id=uuid4()
    )

    assert [item.evidence_ref for item in gathered] == [
        "EV-001",
        "EV-002",
        "EV-003",
        "EV-004",
    ]
    assert source.calls == [
        "crm_list_account_activities",
        "product_get_usage_summary",
        "support_get_open_issues",
    ]


def test_retrieval_itself_involves_no_model() -> None:
    """The LLM chooses *which* evidence to gather, never *what it says*."""
    selection = EvidenceSelection(
        requests=(EvidenceRequest(source=EvidenceSourceName.SUPPORT, reason="x"),)
    )
    gathered = researcher.gather(
        selection, source=InMemoryEvidenceSource(), account_id=uuid4(), opportunity_id=uuid4()
    )
    assert gathered[0].record.content == {"tool": "support_get_open_issues"}


# ---------------------------------------------------------------------------
# Analyst
# ---------------------------------------------------------------------------
def test_hypotheses_citing_known_evidence_are_accepted() -> None:
    accepted = analyst.accept_hypotheses(a_hypothesis_set(), frozenset({"EV-001", "EV-002"}))
    assert accepted == a_hypothesis_set()


def test_hypotheses_citing_unknown_evidence_are_rejected() -> None:
    with pytest.raises(FabricatedCitationError):
        analyst.accept_hypotheses(a_hypothesis_set(), frozenset({"EV-001"}))


def test_impact_assessment_reaches_the_documented_figures() -> None:
    """The same numbers Session 1 pinned, now reached through the agent."""
    impact = analyst.assess_impact(
        amount=Decimal("180000.00"),
        currency="USD",
        probability=Decimal("0.6000"),
        days_inactive=14,
        stage=OpportunityStage.PROPOSAL,
        usage_growth=Decimal("0.4000"),
    )

    assert impact.weighted_value == Decimal("108000.00")
    assert impact.at_risk_value == Decimal("32130.00")


def test_the_impact_agent_takes_no_llm_client() -> None:
    """Not "does not use one" -- cannot be given one."""
    import inspect

    parameters = inspect.signature(analyst.assess_impact).parameters
    assert "llm" not in parameters


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def a_context(llm: LLMClient) -> nodes.NodeContext:
    return nodes.NodeContext(
        llm=llm,
        evidence_source=InMemoryEvidenceSource(),
        model_id="claude-opus-5",
        effort="high",
    )


def test_the_plan_node_writes_the_plan_to_state(
    make_stub_llm: Callable[[dict[str, BaseModel]], LLMClient],
) -> None:
    result = nodes.plan_investigation(
        a_state(), a_context(make_stub_llm({nodes.PLAN_NODE: a_plan()}))
    )
    assert result.state.plan == a_plan()
    assert result.llm_response is not None


def test_the_evidence_node_requires_a_plan(
    make_stub_llm: Callable[[dict[str, BaseModel]], LLMClient],
) -> None:
    with pytest.raises(ValueError, match="requires a plan"):
        nodes.collect_evidence(a_state(), a_context(make_stub_llm({})))


def test_the_impact_node_reports_no_model_call(
    make_stub_llm: Callable[[dict[str, BaseModel]], LLMClient],
) -> None:
    """`llm_response is None` is what becomes `model_call_id = NULL`."""
    result = nodes.calculate_impact(a_state(), a_context(make_stub_llm({})))

    assert result.llm_response is None
    assert result.state.impact is not None
    assert result.state.impact.at_risk_value == Decimal("32130.00")


def test_state_is_frozen_so_a_node_cannot_mutate_a_sibling() -> None:
    state = a_state()
    with pytest.raises((AttributeError, TypeError)):
        state.plan = a_plan()  # type: ignore[misc]


def test_state_digest_changes_only_when_the_state_does() -> None:
    """Two `a_state()` calls would differ only in their random ids -- which the digest
    correctly notices -- so identity is held fixed and content is what varies."""
    state = a_state()

    assert state.digest() == state.digest()
    assert state.digest() != state.with_plan(a_plan()).digest()
    assert state.with_plan(a_plan()).digest() == state.with_plan(a_plan()).digest()


# ---------------------------------------------------------------------------
# Thinness -- the guard against framework absorption (ADR-0002)
# ---------------------------------------------------------------------------
def _nodes_module_tree() -> ast.Module:
    path = PROJECT_ROOT / "src" / "revenue_sentinel" / "orchestration" / "nodes.py"
    return ast.parse(path.read_text(encoding="utf-8"))


def test_node_bodies_import_no_persistence() -> None:
    """A node that can reach a session is a node that will eventually use one."""
    imported: set[str] = set()
    for node in ast.walk(_nodes_module_tree()):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {"sqlalchemy", "revenue_sentinel.db"}
    offenders = {name for name in imported for bad in forbidden if name.startswith(bad)}
    assert not offenders, f"nodes.py imports persistence: {offenders}"


@pytest.mark.parametrize("node_name", list(nodes.NODE_SEQUENCE))
def test_node_bodies_stay_thin(node_name: str) -> None:
    """A fat node is the leading indicator of framework absorption."""
    functions = {
        item.name: item for item in _nodes_module_tree().body if isinstance(item, ast.FunctionDef)
    }
    body = functions[node_name].body
    statements = [item for item in body if not isinstance(item, ast.Expr)]

    assert len(statements) <= MAX_NODE_STATEMENTS, (
        f"{node_name} has {len(statements)} statements; logic belongs in a service"
    )
