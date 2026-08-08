"""`make demo` -- the golden scenario end to end, offline and for free.

Everything here is SIMULATED and every executed result says so. No external system is
contacted, no model is called, and nothing is sent: the email step produces a **draft**,
because sending is not a capability this system has.

The demo is destructive by design -- it resets the local database so the scenario starts
from `INC-001` every time -- so it asks first (rule 19). `DEMO_RESET=yes` skips the
prompt for CI; nothing else does.

It proves four things in order:

1. a Tier 1 action executes automatically,
2. a Tier 2 action **pauses** for a person,
3. resuming works from persisted rows alone (ADR-0016),
4. re-running produces **zero** duplicate effects (ADR-0017).
"""

from __future__ import annotations

import os
import sys

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import Settings, get_settings
from revenue_sentinel.core.logging import configure_logging
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import investigation as inv_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.seeding import seed_database
from revenue_sentinel.db.session import build_engine, build_session_factory, session_scope
from revenue_sentinel.events.pipeline import run_ingestion_cycle
from revenue_sentinel.execution.service import summarise
from revenue_sentinel.governance import approval_service
from revenue_sentinel.orchestration.runner import resume_investigation, run_investigation

APPROVER = "usr:revenue-lead"
INCIDENT = "INC-001"
RULE = "=" * 78


def heading(text: str) -> None:
    print(f"\n{RULE}\n{text}\n{RULE}")


def confirm_reset() -> bool:
    if os.environ.get("DEMO_RESET") == "yes":
        return True
    if not sys.stdin.isatty():
        print("Refusing to reset the database without confirmation.")
        print("Run interactively, or set DEMO_RESET=yes if this database is disposable.")
        return False
    answer = input("This DELETES all local data and reseeds. Continue? [y/N] ").strip()
    return answer.lower() == "y"


def reset_database(settings: Settings) -> None:
    """Empty the business tables and restart the reference sequences.

    Deliberately **not** `alembic downgrade base`. Migrations 0004 and 0006 refuse to
    downgrade a database holding a recorded refusal or an indeterminate action -- which
    is correct, and exactly the state a previous demo run leaves behind. Fighting those
    guards to reset a demo would mean weakening them.

    `TRUNCATE ... RESTART IDENTITY CASCADE` clears the data without touching the schema,
    and the two reference sequences are restarted explicitly because the incident ref is
    part of the prompt digest: a run numbered `INC-002` misses the hand-authored fixture.
    """
    tables = (
        "action_records, approval_requests, policy_evaluations, interventions, "
        "impact_assessments, hypothesis_evidence, hypotheses, evidence_items, "
        "agent_decisions, model_calls, tool_calls, workflow_transitions, workflow_runs, "
        "audit_events, incidents, signals, normalized_events, raw_events, "
        "activities, usage_snapshots, engagement_events, support_issues, "
        "company_profiles, opportunities, accounts"
    )
    engine = build_engine(settings)
    with engine.begin() as connection:
        connection.execute(sa.text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        connection.execute(sa.text("ALTER SEQUENCE incident_ref_seq RESTART WITH 1"))
        connection.execute(sa.text("ALTER SEQUENCE approval_ref_seq RESTART WITH 1"))
    engine.dispose()


def print_interventions(session: Session, run_id: object) -> None:
    rows = session.scalars(
        sa.select(inv_orm.Intervention)
        .where(inv_orm.Intervention.run_id == run_id)
        .order_by(inv_orm.Intervention.rank)
    ).all()

    for row in rows:
        evaluation = session.scalar(
            sa.select(gov_orm.PolicyEvaluation).where(
                gov_orm.PolicyEvaluation.intervention_id == row.id
            )
        )
        decision = evaluation.decision.value.upper() if evaluation else "?"
        tier = int(evaluation.risk_tier) if evaluation else -1
        print(f"  {row.rank}. {row.title}")
        print(
            f"     action {row.action_type.value:<20} expected {row.expected_value} "
            f"score {row.composite_score}"
        )
        print(f"     POLICY {decision:<17} tier {tier}")


def print_action_records(session: Session, run_id: object) -> None:
    rows = session.scalars(
        sa.select(gov_orm.ActionRecord).where(gov_orm.ActionRecord.run_id == run_id)
    ).all()

    if not rows:
        print("  (none yet)")
        return

    for row in rows:
        status = (row.result or {}).get("integration_status", "?")
        print(
            f"  {row.action_type.value:<22} {row.status.value:<10} "
            f"attempts={row.attempt_count}  [{status}]"
        )
        print(f"     target {row.target_ref}   idempotency {row.idempotency_key[:16]}...")


def print_approval_history(session: Session) -> None:
    for view in approval_service.list_requests(
        session, now=get_settings().evaluation_timestamp, pending_only=False
    ):
        print(f"  {view.approval_ref}  {view.effective_status.value:<9} {view.intervention_title}")
        print(f"     requested by {view.requested_by}   expires {view.expires_at.isoformat()}")


def print_audit_timeline(session: Session) -> None:
    rows = session.scalars(
        sa.select(obs_orm.AuditEvent).order_by(obs_orm.AuditEvent.occurred_at)
    ).all()
    for row in rows:
        print(f"  {row.occurred_at.isoformat()}  {row.event_type:<28} {row.actor}")


def run(settings: Settings) -> int:
    factory = build_session_factory(build_engine(settings))

    heading("1/6  SEED AND INGEST -- SIMULATED source feed")
    with session_scope(factory) as session:
        seed_database(session, seed=settings.seed, evaluated_at=settings.evaluation_timestamp)
        summary = run_ingestion_cycle(
            session, evaluated_at=settings.evaluation_timestamp, settings=settings
        )
    print(f"  signals {summary.signals_created}   incidents {summary.incident_refs}")

    heading("2/6  INVESTIGATE -- offline fixtures, no API key, no network")
    with session_scope(factory) as session:
        outcome = run_investigation(session, INCIDENT, settings=settings)
        run_id = outcome.run_id
        impact = outcome.state.impact
        print(f"  evidence {len(outcome.state.evidence)}   hypotheses 2")
        if impact is not None:
            print(f"  weighted {impact.weighted_value} {impact.currency}")
            print(f"  AT RISK  {impact.at_risk_value} {impact.currency}")

        print("\n  INTERVENTIONS (ranked by analytics/, not by the model)")
        print_interventions(session, run_id)

        print("\n  EXECUTION")
        print(f"  {summarise(outcome.execution)}")
        print_action_records(session, run_id)

    heading("3/6  PAUSED -- a person must decide")
    with session_scope(factory) as session:
        pending = approval_service.list_requests(
            session, now=settings.evaluation_timestamp, pending_only=True
        )
        for view in pending:
            print(f"  {view.approval_ref}  {view.intervention_title}")
        approval_ref = pending[0].approval_ref if pending else None

    if approval_ref is None:
        print("  expected a pending approval and found none")
        return 1
    print(f"\n  Run:  uv run rs approve {approval_ref} --as {APPROVER}")

    heading(f"4/6  APPROVE {approval_ref}")
    with session_scope(factory) as session:
        approval_service.decide(
            session,
            approval_service.get_by_ref(session, approval_ref),
            approved=True,
            decided_by=APPROVER,
            occurred_at=settings.evaluation_timestamp,
        )
    print(f"  {approval_ref} approved by {APPROVER}")
    print("  NOTE: a CLAIMED identity, not an authenticated one (ADR-0018).")

    heading("5/6  RESUME -- from persisted business state only (ADR-0016)")
    with session_scope(factory) as session:
        phase = resume_investigation(session, INCIDENT, settings=settings)
        print(f"  {summarise(phase)}")
        print_action_records(session, run_id)

    heading("6/6  RE-RUN -- proving zero duplicate effects (ADR-0017)")
    with session_scope(factory) as session:
        again = resume_investigation(session, INCIDENT, settings=settings)
        total = session.scalar(
            sa.select(sa.func.count())
            .select_from(gov_orm.ActionRecord)
            .where(gov_orm.ActionRecord.run_id == run_id)
        )
        print(f"  performed this pass: {len(again.performed)}   total action records: {total}")

    with session_scope(factory) as session:
        heading("ACTION RECORDS")
        print_action_records(session, run_id)
        heading("APPROVAL HISTORY")
        print_approval_history(session)
        heading("AUDIT TIMELINE")
        print_audit_timeline(session)

    heading("DONE")
    print("  Every result above is SIMULATED. No external system was contacted.")
    print("  One CRM task and one UNSENT email draft. Nothing was sent -- there is no")
    print("  tool that could send. $0 spent, no model call.")
    return 0


def main() -> int:
    settings = get_settings()
    if settings.demo_mode != "fixture":
        print(f"make demo runs offline only. DEMO_MODE is {settings.demo_mode!r}.")
        return 1

    # The demo *is* the output. Structured JSON logs interleaved with it would make
    # the narrative unreadable, so they are raised to WARNING for this script only.
    configure_logging(level="WARNING", log_format=settings.log_format)

    if not confirm_reset():
        return 1
    reset_database(settings)
    return run(settings)


if __name__ == "__main__":
    raise SystemExit(main())
