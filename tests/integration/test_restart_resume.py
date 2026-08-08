"""Resume after the original runtime is genuinely gone (ADR-0016).

This is the test that earns the phrase "restart safe", so it is deliberately awkward: it
does not reuse the suite's `detected` / `investigated` fixtures, because those hold a
live `Session` inside a rolled-back outer transaction. Resuming inside the same
transaction would prove nothing at all -- the data would still be sitting in memory,
visible only to the connection that wrote it.

Instead it:

1. commits a real investigation through a session it then **closes and drops**,
2. discards the runner's client, adapters, graph, and LangGraph checkpoint with it,
3. opens a **new engine and a new session** against the same database,
4. approves and resumes from persisted rows alone.

Nothing survives the boundary except what is in PostgreSQL. If resume needed anything
held in memory -- a checkpoint, a cached graph, a live client -- step 4 would fail.

Cleanup is explicit because this module writes committed data the rest of the suite
would otherwise inherit.
"""

from __future__ import annotations

import gc
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings
from revenue_sentinel.db.models import events as events_orm
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import gtm as gtm_orm
from revenue_sentinel.db.models import investigation as orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.db.seeding import seed_database
from revenue_sentinel.domain.enums import (
    ActionStatus,
    ActionType,
    IncidentStatus,
    WorkflowStatus,
)
from revenue_sentinel.events.pipeline import run_ingestion_cycle
from revenue_sentinel.governance import approvals
from revenue_sentinel.orchestration import runner

APPROVER = "usr:revenue-lead"


@pytest.fixture
def committed_run(engine: Engine, settings: Settings) -> Iterator[tuple[UUID, str]]:
    """A real, **committed** investigation, left paused awaiting approval.

    The session that produced it is closed before the fixture yields, so no caller can
    accidentally reuse it.
    """
    _reset_reference_sequences(engine)

    with Session(engine) as setup:
        seed_database(setup, seed=settings.seed, evaluated_at=settings.evaluation_timestamp)
        run_ingestion_cycle(setup, evaluated_at=settings.evaluation_timestamp, settings=settings)
        # The incident-ref sequence is monotonic across fixture uses, so the ref is read
        # back rather than assumed -- a hardcoded "INC-001" passes once and then errors.
        incident_ref = setup.scalar(
            sa.select(workflow_orm.Incident.incident_ref).order_by(
                workflow_orm.Incident.opened_at.desc()
            )
        )
        assert incident_ref is not None
        outcome = runner.run_investigation(setup, incident_ref, settings=settings)
        run_id = outcome.run_id
        assert isinstance(run_id, UUID)
        setup.commit()

    yield run_id, incident_ref

    with Session(engine) as teardown:
        teardown.execute(sa.delete(gov_orm.ActionRecord))
        teardown.execute(sa.delete(gov_orm.ApprovalRequest))
        teardown.execute(sa.delete(gov_orm.PolicyEvaluation))
        teardown.execute(sa.delete(orm.Intervention))
        teardown.execute(sa.delete(workflow_orm.WorkflowRun))
        teardown.execute(sa.delete(workflow_orm.Incident))
        teardown.execute(sa.delete(events_orm.Signal))
        teardown.execute(sa.delete(events_orm.NormalizedEvent))
        teardown.execute(sa.delete(events_orm.RawEvent))
        for model in (
            gtm_orm.Activity,
            gtm_orm.UsageSnapshot,
            gtm_orm.EngagementEvent,
            gtm_orm.SupportIssue,
            gtm_orm.CompanyProfile,
            gtm_orm.Opportunity,
            gtm_orm.Account,
        ):
            teardown.execute(sa.delete(model))
        teardown.commit()

    _reset_reference_sequences(engine)


def _reset_reference_sequences(engine: Engine) -> None:
    """Restart `INC-` and `APR-` numbering.

    This module commits real rows, so the sequences advance for everyone. The incident
    reference is part of the prompt digest, so a run numbered `INC-002` misses the
    hand-authored fixture -- correct behaviour from fixture mode, and a confusing way for
    this test to fail. The fixture owns its committed data; it owns restoring the
    counters too.
    """
    with engine.begin() as connection:
        connection.execute(sa.text("ALTER SEQUENCE incident_ref_seq RESTART WITH 1"))
        connection.execute(sa.text("ALTER SEQUENCE approval_ref_seq RESTART WITH 1"))


def fresh_session(database_url: str) -> tuple[Any, Session]:
    """A brand-new engine and session. Shares nothing with the process that paused.

    A new `Engine` means a new connection pool and new connections -- not the pooled
    connection the paused run used. That is the part that makes this a restart rather
    than a re-read.
    """
    from revenue_sentinel.db.session import build_session_factory

    new_engine = sa.create_engine(database_url, pool_pre_ping=True)
    return new_engine, build_session_factory(new_engine)()


def test_a_paused_run_resumes_from_persisted_rows_after_the_runtime_is_destroyed(
    committed_run: tuple[UUID, str], settings: Settings, migrated_database_url: str
) -> None:
    """The whole of ADR-0016, in one test."""
    run_id, incident_ref = committed_run

    # --- the original runtime is gone -------------------------------------------------
    # `committed_run` already closed its session. Force a collection so any lingering
    # graph, client, or checkpoint object is genuinely unreachable rather than merely
    # out of scope.
    gc.collect()

    # --- a completely fresh runtime ---------------------------------------------------
    engine_a, paused = fresh_session(migrated_database_url)
    try:
        run = paused.get(workflow_orm.WorkflowRun, run_id)
        assert run is not None
        assert run.status is WorkflowStatus.INTERRUPTED, "the run should be paused"
        assert run.ended_at is None

        incident = paused.scalar(
            sa.select(workflow_orm.Incident).where(
                workflow_orm.Incident.incident_ref == incident_ref
            )
        )
        assert incident is not None
        assert incident.status is IncidentStatus.AWAITING_APPROVAL

        # The Tier 1 CRM task ran before the pause and is durable.
        records = paused.scalars(
            sa.select(gov_orm.ActionRecord).where(gov_orm.ActionRecord.run_id == run_id)
        ).all()
        assert len(records) == 1
        assert records[0].action_type is ActionType.CRM_TASK
        assert records[0].status is ActionStatus.SUCCEEDED

        request = paused.scalar(
            sa.select(gov_orm.ApprovalRequest).where(gov_orm.ApprovalRequest.run_id == run_id)
        )
        assert request is not None
        assert request.approval_ref.startswith("APR-")

        approvals.decide(
            paused,
            request,
            approved=True,
            decided_by=APPROVER,
            occurred_at=settings.evaluation_timestamp,
        )
        paused.commit()
    finally:
        paused.close()
        engine_a.dispose()

    # --- a second fresh runtime, resuming ---------------------------------------------
    gc.collect()
    engine_b, resumed = fresh_session(migrated_database_url)
    try:
        phase = runner.resume_investigation(resumed, incident_ref, settings=settings)
        resumed.commit()

        assert phase.is_complete, "resume should have nothing left waiting"
        assert len(phase.performed) == 1, "exactly the email draft, performed once"

        records = resumed.scalars(
            sa.select(gov_orm.ActionRecord).where(gov_orm.ActionRecord.run_id == run_id)
        ).all()
        by_type = {record.action_type: record for record in records}

        assert len(records) == 2, "one CRM task, one email draft, and nothing else"
        assert set(by_type) == {ActionType.CRM_TASK, ActionType.EMAIL_DRAFT}
        assert all(record.status is ActionStatus.SUCCEEDED for record in records)

        # Rule 5, on the thing that actually acted.
        for record in records:
            assert (record.result or {}).get("integration_status") == "SIMULATED"

        # The draft is a draft. Nothing was sent, and there is no tool that could.
        draft_result = by_type[ActionType.EMAIL_DRAFT].result or {}
        assert "sent_at" not in str(draft_result)

        run = resumed.get(workflow_orm.WorkflowRun, run_id)
        assert run is not None
        assert run.status is WorkflowStatus.COMPLETED
        assert run.ended_at is not None
    finally:
        resumed.close()
        engine_b.dispose()


def test_resume_does_not_re_run_the_investigation_nodes(
    committed_run: tuple[UUID, str], settings: Settings, migrated_database_url: str
) -> None:
    """Resume is not replay. No node runs again, so no model call site is exercised.

    If resume replayed the graph it would produce a second set of evidence rows, a
    second batch of model calls, and more transitions -- each of which is asserted
    unchanged here.
    """
    run_id, incident_ref = committed_run
    gc.collect()

    engine_a, paused = fresh_session(migrated_database_url)
    try:
        counts_before = _counts(paused, run_id)
        request = paused.scalar(
            sa.select(gov_orm.ApprovalRequest).where(gov_orm.ApprovalRequest.run_id == run_id)
        )
        assert request is not None
        approvals.decide(
            paused,
            request,
            approved=True,
            decided_by=APPROVER,
            occurred_at=settings.evaluation_timestamp,
        )
        paused.commit()
    finally:
        paused.close()
        engine_a.dispose()

    gc.collect()
    engine_b, resumed = fresh_session(migrated_database_url)
    try:
        runner.resume_investigation(resumed, incident_ref, settings=settings)
        resumed.commit()
        counts_after = _counts(resumed, run_id)
    finally:
        resumed.close()
        engine_b.dispose()

    assert counts_after["evidence"] == counts_before["evidence"]
    assert counts_after["hypotheses"] == counts_before["hypotheses"]
    assert counts_after["model_calls"] == counts_before["model_calls"]
    assert counts_after["transitions"] == counts_before["transitions"]
    assert counts_after["interventions"] == counts_before["interventions"]


def test_resuming_twice_creates_no_second_effect(
    committed_run: tuple[UUID, str], settings: Settings, migrated_database_url: str
) -> None:
    """Idempotency, not the framework, is what makes a repeated resume safe."""
    run_id, incident_ref = committed_run
    gc.collect()

    engine_a, session = fresh_session(migrated_database_url)
    try:
        request = session.scalar(
            sa.select(gov_orm.ApprovalRequest).where(gov_orm.ApprovalRequest.run_id == run_id)
        )
        assert request is not None
        approvals.decide(
            session,
            request,
            approved=True,
            decided_by=APPROVER,
            occurred_at=settings.evaluation_timestamp,
        )
        runner.resume_investigation(session, incident_ref, settings=settings)
        session.commit()
    finally:
        session.close()
        engine_a.dispose()

    gc.collect()
    engine_b, again = fresh_session(migrated_database_url)
    try:
        second = runner.resume_investigation(again, incident_ref, settings=settings)
        again.commit()

        assert second.performed == (), "a second resume must perform nothing"
        total = again.scalar(
            sa.select(sa.func.count())
            .select_from(gov_orm.ActionRecord)
            .where(gov_orm.ActionRecord.run_id == run_id)
        )
        assert total == 2
    finally:
        again.close()
        engine_b.dispose()


def _counts(session: Session, run_id: UUID) -> dict[str, int]:
    from revenue_sentinel.db.models import observability as obs_orm

    def count(model: Any, column: Any) -> int:
        value = session.scalar(
            sa.select(sa.func.count()).select_from(model).where(column == run_id)
        )
        return int(value or 0)

    return {
        "evidence": count(orm.EvidenceItem, orm.EvidenceItem.run_id),
        "hypotheses": count(orm.Hypothesis, orm.Hypothesis.run_id),
        "model_calls": count(obs_orm.ModelCall, obs_orm.ModelCall.run_id),
        "transitions": count(
            workflow_orm.WorkflowTransition, workflow_orm.WorkflowTransition.run_id
        ),
        "interventions": count(orm.Intervention, orm.Intervention.run_id),
    }
