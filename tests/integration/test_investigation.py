"""The investigation graph, end to end against the golden scenario.

Acceptance criteria 1-8: the graph runs, transitions are written before the next node,
every LLM call is schema-validated, hypotheses cite real evidence, impact comes from
`analytics/`, fixture mode makes no network call, untrusted content stays delimited,
and the incident advances.

Everything here runs offline against hand-authored fixtures. **No live API call is
made, and none has ever been made by this project** -- see ADR-0013.
"""

from __future__ import annotations

import socket
import sys
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.core.errors import FabricatedCitationError
from revenue_sentinel.db.models import investigation as inv_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.domain.enums import ComputedBy, IncidentStatus, TrustLevel, WorkflowStatus
from revenue_sentinel.events.pipeline import run_ingestion_cycle
from revenue_sentinel.intelligence.fixture_client import FIXTURE_STOP_REASON
from revenue_sentinel.orchestration import runner
from revenue_sentinel.orchestration.nodes import NODE_SEQUENCE
from revenue_sentinel.orchestration.runner import (
    IncidentNotInvestigableError,
    run_investigation,
)
from revenue_sentinel.orchestration.transitions import GRAPH_ENTRY, GRAPH_EXIT_NODE

EXPECTED_EVIDENCE_ITEMS = 6
EXPECTED_HYPOTHESES = 2
EXPECTED_TRANSITIONS = 5
EXPECTED_MODEL_CALLS = 3


@pytest.fixture
def detected(
    seeded_session: Session, settings: Settings, evaluation_timestamp: datetime
) -> Session:
    """A seeded database with INC-001 open and triaged."""
    run_ingestion_cycle(seeded_session, evaluated_at=evaluation_timestamp, settings=settings)
    return seeded_session


@pytest.fixture
def investigated(detected: Session, settings: Settings) -> runner.InvestigationOutcome:
    return run_investigation(detected, "INC-001", settings=settings)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def test_the_graph_produces_the_documented_plan(
    investigated: runner.InvestigationOutcome,
) -> None:
    plan = investigated.state.plan

    assert plan is not None
    assert len(plan.steps) == 5
    sources = [step.source.value for step in plan.steps]
    assert sources == sorted(sources, key=lambda name: sources.index(name))
    assert "product_get_usage_summary" in sources
    assert "support_get_open_issues" in sources


def test_six_evidence_items_across_at_least_three_source_systems(
    investigated: runner.InvestigationOutcome,
) -> None:
    """`docs/demo-scenario.md` §2, behaviour 4."""
    evidence = investigated.state.evidence

    assert len(evidence) == EXPECTED_EVIDENCE_ITEMS
    systems = {item.record.source_system for item in evidence}
    assert len(systems) >= 3

    refs = [item.evidence_ref for item in evidence]
    assert refs == ["EV-001", "EV-002", "EV-003", "EV-004", "EV-005", "EV-006"]


def test_two_hypotheses_each_citing_real_evidence(
    investigated: runner.InvestigationOutcome,
) -> None:
    """`docs/demo-scenario.md` §2, behaviour 5."""
    hypotheses = investigated.state.hypotheses
    assert hypotheses is not None
    assert len(hypotheses.hypotheses) == EXPECTED_HYPOTHESES

    known = investigated.state.known_evidence_refs
    for draft in hypotheses.hypotheses:
        assert draft.cites
        assert set(draft.cites) <= known


def test_the_impact_figures_match_the_demo_document(
    investigated: runner.InvestigationOutcome,
) -> None:
    """`docs/demo-scenario.md` §2, behaviour 6 -- $108,000 weighted, $32,130 at risk."""
    impact = investigated.state.impact

    assert impact is not None
    assert impact.pipeline_value == Decimal("180000.00")
    assert impact.weighted_value == Decimal("108000.00")
    assert impact.at_risk_value == Decimal("32130.00")


def test_the_run_is_recorded_as_completed(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    run = detected.get(workflow_orm.WorkflowRun, investigated.run_id)

    assert run is not None
    assert run.status is WorkflowStatus.COMPLETED
    assert run.graph_version == "investigation/v1"
    assert run.ended_at is not None


# ---------------------------------------------------------------------------
# Transitions -- written before the next node runs
# ---------------------------------------------------------------------------
def test_transitions_are_gapless_and_in_node_order(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    rows = detected.scalars(
        sa.select(workflow_orm.WorkflowTransition)
        .where(workflow_orm.WorkflowTransition.run_id == investigated.run_id)
        .order_by(workflow_orm.WorkflowTransition.sequence)
    ).all()

    assert len(rows) == EXPECTED_TRANSITIONS
    assert [row.sequence for row in rows] == list(range(EXPECTED_TRANSITIONS))
    assert [row.to_node for row in rows] == [*NODE_SEQUENCE, GRAPH_EXIT_NODE]
    assert rows[0].from_node == GRAPH_ENTRY


def test_every_transition_carries_a_state_digest(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """Digests must differ as state accumulates -- an unchanging digest would mean
    the recorder was hashing something that is not the state."""
    digests = detected.scalars(
        sa.select(workflow_orm.WorkflowTransition.state_digest)
        .where(workflow_orm.WorkflowTransition.run_id == investigated.run_id)
        .order_by(workflow_orm.WorkflowTransition.sequence)
    ).all()

    assert all(len(digest) == 64 for digest in digests)
    assert len(set(digests)) == EXPECTED_TRANSITIONS


def test_a_transition_exists_before_the_node_that_follows_it_persists_anything(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """The chain is complete from graph entry to graph exit."""
    rows = detected.scalars(
        sa.select(workflow_orm.WorkflowTransition)
        .where(workflow_orm.WorkflowTransition.run_id == investigated.run_id)
        .order_by(workflow_orm.WorkflowTransition.sequence)
    ).all()

    for previous, current in pairwise(rows):
        assert current.from_node == previous.to_node


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def test_evidence_is_persisted_as_untrusted(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    rows = detected.scalars(
        sa.select(inv_orm.EvidenceItem).where(inv_orm.EvidenceItem.run_id == investigated.run_id)
    ).all()

    assert len(rows) == EXPECTED_EVIDENCE_ITEMS
    assert {row.trust_level for row in rows} == {TrustLevel.UNTRUSTED}


def test_every_citation_points_at_a_real_evidence_row(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """The structural half of the anti-hallucination gate: foreign keys."""
    orphans = detected.scalar(
        sa.select(sa.func.count())
        .select_from(inv_orm.HypothesisEvidence)
        .where(
            inv_orm.HypothesisEvidence.evidence_item_id.not_in(sa.select(inv_orm.EvidenceItem.id))
        )
    )
    assert orphans == 0
    assert investigated.persisted.citations >= EXPECTED_HYPOTHESES


def test_the_impact_assessment_records_its_provenance_and_inputs(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    assessment = detected.scalar(
        sa.select(inv_orm.ImpactAssessment).where(
            inv_orm.ImpactAssessment.run_id == investigated.run_id
        )
    )

    assert assessment is not None
    assert assessment.computed_by is ComputedBy.DETERMINISTIC
    assert assessment.at_risk_value == Decimal("32130.00")
    assert assessment.inputs["method_version"] == "pipeline_impact/v1"
    assert assessment.inputs["bands_version"] == "risk_bands/v1"


def test_only_the_llm_backed_nodes_record_a_model_call(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """This is the Session 8 `no_llm_arithmetic` query, run early."""
    decisions = detected.scalars(
        sa.select(workflow_orm.AgentDecision).where(
            workflow_orm.AgentDecision.run_id == investigated.run_id
        )
    ).all()

    by_node = {decision.decision_type: decision.model_call_id for decision in decisions}

    assert len(by_node) == len(NODE_SEQUENCE)
    assert by_node["calculate_impact"] is None
    assert by_node["plan_investigation"] is not None
    assert by_node["collect_evidence"] is not None
    assert by_node["generate_hypotheses"] is not None


def test_no_model_call_is_attributed_to_the_arithmetic_node(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    nodes_with_calls = set(
        detected.scalars(
            sa.select(obs_orm.ModelCall.node_name).where(
                obs_orm.ModelCall.run_id == investigated.run_id
            )
        ).all()
    )
    assert "calculate_impact" not in nodes_with_calls
    assert len(nodes_with_calls) == EXPECTED_MODEL_CALLS


# ---------------------------------------------------------------------------
# Fixture-mode honesty (ADR-0013)
# ---------------------------------------------------------------------------
def test_replayed_model_calls_claim_no_usage(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """Zero tokens because zero were consumed. Nothing here is estimated."""
    rows = detected.scalars(
        sa.select(obs_orm.ModelCall).where(obs_orm.ModelCall.run_id == investigated.run_id)
    ).all()

    assert len(rows) == EXPECTED_MODEL_CALLS
    for row in rows:
        assert row.is_replay is True
        assert row.input_tokens == 0
        assert row.output_tokens == 0
        assert row.cache_read_tokens == 0
        assert row.cache_write_tokens == 0
        assert row.stop_reason == FIXTURE_STOP_REASON


def test_a_whole_run_completes_with_the_network_unavailable(
    detected: Session, settings: Settings
) -> None:
    """The strongest form of the offline claim: sockets are refused outright."""

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("fixture mode attempted a network connection")

    original = socket.socket
    socket.socket = refuse  # type: ignore[assignment, misc]
    try:
        outcome = run_investigation(detected, "INC-001", settings=settings)
    finally:
        socket.socket = original  # type: ignore[misc]

    assert outcome.state.impact is not None


def test_the_anthropic_sdk_is_never_imported_during_an_offline_run(
    detected: Session, settings: Settings
) -> None:
    sys.modules.pop("anthropic", None)

    run_investigation(detected, "INC-001", settings=settings)

    assert "anthropic" not in sys.modules


# ---------------------------------------------------------------------------
# Fabricated citations reject before persistence
# ---------------------------------------------------------------------------
def test_a_fabricated_citation_aborts_the_run_and_persists_nothing(
    detected: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance criterion 4.

    The model is made to cite `EV-999`, which no evidence item carries. The run must
    fail before persistence -- a partially written investigation would be worse than
    none, because it would look complete.
    """
    from revenue_sentinel.agents import analyst
    from revenue_sentinel.intelligence.schemas import HypothesisDraft, HypothesisSet

    fabricated = HypothesisSet(
        hypotheses=(
            HypothesisDraft(
                rank=1, statement="cites reality", confidence=Decimal("0.6"), cites=("EV-001",)
            ),
            HypothesisDraft(
                rank=2, statement="cites nothing", confidence=Decimal("0.5"), cites=("EV-999",)
            ),
        )
    )
    real_generate = analyst.generate_hypotheses

    def poisoned(*args: Any, **kwargs: Any) -> Any:
        response = real_generate(*args, **kwargs)
        return type(response)(
            output=fabricated,
            model_id=response.model_id,
            effort=response.effort,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            stop_reason=response.stop_reason,
            is_replay=response.is_replay,
            prompt_digest=response.prompt_digest,
        )

    monkeypatch.setattr(analyst, "generate_hypotheses", poisoned)

    with pytest.raises(FabricatedCitationError, match="EV-999"):
        run_investigation(detected, "INC-001", settings=settings)

    detected.rollback()
    assert detected.scalar(sa.select(sa.func.count()).select_from(inv_orm.Hypothesis)) == 0
    assert detected.scalar(sa.select(sa.func.count()).select_from(inv_orm.ImpactAssessment)) == 0
    assert detected.scalar(sa.select(sa.func.count()).select_from(inv_orm.EvidenceItem)) == 0


# ---------------------------------------------------------------------------
# Incident lifecycle
# ---------------------------------------------------------------------------
def test_the_incident_advances_to_analyzed(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    incident = detected.scalar(
        sa.select(workflow_orm.Incident).where(workflow_orm.Incident.incident_ref == "INC-001")
    )
    assert incident is not None
    assert incident.status is IncidentStatus.ANALYZED


def test_each_lifecycle_step_is_audited(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    transitions = detected.scalars(
        sa.select(obs_orm.AuditEvent)
        .where(obs_orm.AuditEvent.event_type == "incident.transitioned")
        .order_by(obs_orm.AuditEvent.occurred_at)
    ).all()

    moves = [(event.payload["from_status"], event.payload["to_status"]) for event in transitions]
    assert ("detected", "triaged") in moves
    assert ("triaged", "investigating") in moves
    assert ("investigating", "analyzed") in moves


def test_re_investigating_an_analyzed_incident_is_refused(
    investigated: runner.InvestigationOutcome, detected: Session, settings: Settings
) -> None:
    """Replay is Session 6 work, so this is refused with an explanation rather than
    half-attempted."""
    with pytest.raises(IncidentNotInvestigableError, match="starts from triaged"):
        run_investigation(detected, "INC-001", settings=settings)


def test_an_unknown_incident_is_refused(detected: Session, settings: Settings) -> None:
    from revenue_sentinel.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        run_investigation(detected, "INC-999", settings=settings)
