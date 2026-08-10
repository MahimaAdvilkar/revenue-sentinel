"""Command-line entry point.

Exposed as the `revenue-sentinel` console script. `scripts/seed.py` is a thin shim
over `seed` so the documented `make seed` target and this CLI cannot drift apart.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import typer

from revenue_sentinel.core.config import get_settings
from revenue_sentinel.core.errors import RevenueSentinelError
from revenue_sentinel.core.logging import configure_logging
from revenue_sentinel.cost import reporting as cost_reporting
from revenue_sentinel.cost.summary import CostSummary, summarise_run
from revenue_sentinel.cost.timeline import incident_timeline
from revenue_sentinel.db.seeding import seed_database
from revenue_sentinel.db.session import build_engine, build_session_factory, session_scope
from revenue_sentinel.domain.enums import ActionStatus
from revenue_sentinel.events.pipeline import run_ingestion_cycle
from revenue_sentinel.execution import reconciliation
from revenue_sentinel.execution.service import summarise as execution_summary
from revenue_sentinel.governance import approval_service
from revenue_sentinel.orchestration.runner import resume_investigation, run_investigation

app = typer.Typer(
    name="revenue-sentinel",
    help="Revenue Sentinel -- Agentic AI GTM Control Tower",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def version() -> None:
    """Print the package version."""
    from importlib.metadata import version as package_version

    typer.echo(package_version("revenue-sentinel"))


@app.command()
def seed() -> None:
    """Load the deterministic synthetic GTM data set.

    Idempotent -- running it twice leaves the database in the same state, not with
    two copies of the fixture set.
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)

    engine = build_engine(settings)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        summary = seed_database(
            session, seed=settings.seed, evaluated_at=settings.evaluation_timestamp
        )

    typer.echo(f"Seeded {summary.total} rows (SEED={settings.seed}) -- all is_simulated=true:")
    typer.echo(f"  accounts           {summary.accounts:>4}")
    typer.echo(f"  opportunities      {summary.opportunities:>4}")
    typer.echo(f"  activities         {summary.activities:>4}")
    typer.echo(f"  usage_snapshots    {summary.usage_snapshots:>4}")
    typer.echo(f"  engagement_events  {summary.engagement_events:>4}")
    typer.echo(f"  support_issues     {summary.support_issues:>4}")
    typer.echo(f"  company_profiles   {summary.company_profiles:>4}")


@app.command()
def ingest() -> None:
    """Run one ingestion cycle: sources -> events -> signals -> incidents.

    The source feed is SIMULATED -- it replays the seeded GTM mirror, not an
    external system. Replay-safe: running it twice creates no duplicate rows.
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)

    engine = build_engine(settings)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        summary = run_ingestion_cycle(
            session, evaluated_at=settings.evaluation_timestamp, settings=settings
        )

    typer.echo(f"Ingestion cycle complete (source feed: {summary.ingestion_status})")
    typer.echo(f"  evaluated at         {summary.evaluated_at.isoformat()}")
    typer.echo(f"  raw events offered   {summary.raw_offered:>4}")
    typer.echo(f"  raw events inserted  {summary.raw_inserted:>4}")
    typer.echo(f"  events normalized    {summary.normalized:>4}")
    typer.echo(f"  opportunities seen   {summary.contexts_evaluated:>4}")
    typer.echo(f"  signals created      {summary.signals_created:>4}")
    typer.echo(f"  signals deduplicated {summary.signals_deduplicated:>4}")
    typer.echo(f"  incidents opened     {summary.incidents_opened:>4}")
    if summary.incident_refs:
        typer.echo(f"  incidents            {', '.join(summary.incident_refs)}")


@app.command()
def investigate(incident_ref: str) -> None:
    """Run the investigation graph against one incident.

    Offline by default: `DEMO_MODE=fixture` replays hand-authored responses and makes
    no network call. A fixture miss raises rather than falling back to a live call.
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)

    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        with session_scope(factory) as session:
            outcome = run_investigation(session, incident_ref, settings=settings)
            state = outcome.state

        typer.echo(f"Investigation complete for {incident_ref} (DEMO_MODE={settings.demo_mode})")
        typer.echo(f"  run                  {outcome.run_id}")
        typer.echo(f"  transitions recorded {outcome.transitions}")

        if state.plan is not None:
            typer.echo(f"\n  PLAN ({len(state.plan.steps)} steps)")
            for step in state.plan.steps:
                typer.echo(f"    {step.order}. {step.source.value}")
                typer.echo(f"       {step.objective}")

        typer.echo(f"\n  EVIDENCE ({len(state.evidence)} items)")
        for item in state.evidence:
            typer.echo(
                f"    {item.evidence_ref}  {item.record.source_system.value:<11} "
                f"{item.record.tool_name}"
            )

        if state.hypotheses is not None:
            typer.echo(f"\n  HYPOTHESES ({len(state.hypotheses.hypotheses)})")
            for draft in sorted(state.hypotheses.hypotheses, key=lambda h: h.rank):
                typer.echo(f"    H{draft.rank} (confidence {draft.confidence})")
                typer.echo(f"       {draft.statement}")
                typer.echo(f"       cites: {', '.join(draft.cites)}")

        if state.impact is not None:
            impact = state.impact
            typer.echo("\n  IMPACT (deterministic -- analytics/, never a model)")
            typer.echo(f"    pipeline value   {impact.pipeline_value} {impact.currency}")
            typer.echo(f"    weighted value   {impact.weighted_value} {impact.currency}")
            typer.echo(f"    stall risk       {impact.applied_stall_risk_factor}")
            typer.echo(f"    at risk (gross)  {impact.at_risk_gross} {impact.currency}")
            typer.echo(f"    usage offset     {impact.applied_usage_offset}")
            typer.echo(f"    AT RISK          {impact.at_risk_value} {impact.currency}")

        if state.interventions:
            typer.echo(
                f"\n  INTERVENTIONS ({len(state.interventions)} ranked -- "
                f"drafted by a model, ordered by analytics/)"
            )
            decisions = {item.draft.title: item.outcome for item in state.policy_decisions}
            for rank, ranked in enumerate(state.interventions, start=1):
                outcome_for = decisions.get(ranked.draft.title)
                typer.echo(f"    {rank}. {ranked.draft.title}")
                typer.echo(
                    f"       action {ranked.draft.action.value}   "
                    f"expected {ranked.score.expected_value} {state.opportunity.currency}   "
                    f"score {ranked.score.composite_score}"
                )
                if outcome_for is not None:
                    typer.echo(
                        f"       POLICY {outcome_for.decision.value.upper():<17} "
                        f"tier {int(outcome_for.risk_tier)}   "
                        f"rules: {', '.join(outcome_for.matched_rules)}"
                    )

            typer.echo(
                "\n  Nothing was executed. Session 5 decides; execution arrives in Session 6."
            )
    except RevenueSentinelError as error:
        # Our own errors are expected conditions with actionable messages. A traceback
        # would bury the message that explains what to do next.
        typer.secho(f"error: {error}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from error


if __name__ == "__main__":  # pragma: no cover -- exercised via the console script
    app()


# ---------------------------------------------------------------------------
# Approvals (Session 6) -- see ADR-0018 on what `--as` does and does not mean
# ---------------------------------------------------------------------------
IDENTITY_WARNING = (
    "NOTE: --as is a CLAIMED identity, not an authenticated one. This system has no "
    "authentication; anyone with shell and database access can claim any actor. "
    "Self-approval prevention stops an accident, not an impersonation (ADR-0018)."
)


@app.command()
def approvals(pending_only: bool = True) -> None:
    """List approval requests awaiting a human decision."""
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    factory = build_session_factory(build_engine(settings))

    with session_scope(factory) as session:
        rows = approval_service.list_requests(
            session, now=settings.evaluation_timestamp, pending_only=pending_only
        )

        if not rows:
            typer.echo("No approval requests.")
            return

        typer.echo(f"{len(rows)} approval request(s):")
        for row in rows:
            typer.echo(
                f"  {row.approval_ref}  {row.effective_status.value:<9} "
                f"expires {row.expires_at.isoformat()}"
            )
            typer.echo(f"      {row.intervention_title}")
            typer.echo(f"      requested by {row.requested_by} -- SIMULATED action")
            typer.echo(f"      approve: uv run rs approve {row.approval_ref} --as usr:your-name")


def _decide(approval_ref: str, actor: str, *, approved: bool, note: str | None) -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    factory = build_session_factory(build_engine(settings))
    verb = "approved" if approved else "rejected"

    try:
        with session_scope(factory) as session:
            request = approval_service.get_by_ref(session, approval_ref)
            approval_service.decide(
                session,
                request,
                approved=approved,
                decided_by=actor,
                occurred_at=settings.evaluation_timestamp,
                note=note,
            )
        typer.echo(f"{approval_ref} {verb} by {actor}")
        typer.secho(IDENTITY_WARNING, fg=typer.colors.YELLOW)
        if approved:
            typer.echo("\nNothing executed yet. Resume the run to act on it:")
            typer.echo("  uv run rs resume INC-001")
    except RevenueSentinelError as error:
        typer.secho(f"error: {error}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from error


@app.command()
def approve(approval_ref: str, actor: str = typer.Option(..., "--as")) -> None:
    """Approve a pending request. `--as` is a claimed identity (ADR-0018)."""
    _decide(approval_ref, actor, approved=True, note=None)


@app.command()
def reject(approval_ref: str, actor: str = typer.Option(..., "--as")) -> None:
    """Reject a pending request. `--as` is a claimed identity (ADR-0018)."""
    _decide(approval_ref, actor, approved=False, note=None)


@app.command()
def resume(incident_ref: str = "INC-001") -> None:
    """Resume a paused run from persisted business state (ADR-0016).

    Not a replay: no investigation node re-runs and no model call site is exercised.
    Only the pending execution phase continues.
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    factory = build_session_factory(build_engine(settings))

    try:
        with session_scope(factory) as session:
            phase = resume_investigation(session, incident_ref, settings=settings)
            summary = execution_summary(phase)
            lines = [
                f"    {result.status.value:<10} {result.payload.get('tool', '?')}"
                f"   {'already done' if result.already_done else 'performed now'}"
                f"   [{result.payload.get('integration_status', '?')}]"
                for result in phase.executed
            ]
            waiting = [item.title for item in phase.awaiting_approval]

        typer.echo(f"Resumed {incident_ref}: {summary}")
        for line in lines:
            typer.echo(line)
        for title in waiting:
            typer.echo(f"    still awaiting approval: {title}")
    except RevenueSentinelError as error:
        typer.secho(f"error: {error}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from error


# ---------------------------------------------------------------------------
# Cost (Session 7)
# ---------------------------------------------------------------------------
CONCURRENCY_NOTE = (
    "Budgets are checked read-then-call and are safe only because model calls are "
    "serialized within a run. Two concurrent runs sharing a GLOBAL budget can race "
    "(ADR-0019)."
)


def render_cost_summary(summary: CostSummary) -> list[str]:
    """Microdollar precision throughout -- rounding a governance figure to cents is how
    real sub-cent spend becomes an invisible $0.00."""
    lines = [
        f"  model calls        {summary.model_calls}",
        f"  tool calls         {summary.tool_calls}",
        f"  model cost         ${summary.model_cost}",
        f"  tool cost          ${summary.tool_cost}   (SIMULATED adapters bill nothing)",
        f"  TOTAL              ${summary.total_cost}",
        f"  pricing version    {', '.join(summary.pricing_versions) or '(no entries)'}",
    ]
    if summary.budgets:
        lines.append("  budgets")
        for budget in summary.budgets:
            scope = budget.scope.value + (f":{budget.scope_ref}" if budget.scope_ref else "")
            lines.append(
                f"    {scope:<28} limit ${budget.limit_usd}  consumed "
                f"${budget.consumed_usd}  remaining ${budget.remaining_usd}"
                + ("" if budget.hard_stop else "  [soft]")
            )
    else:
        lines.append("  budgets            none configured (unbudgeted, not blocked)")
    return lines


@app.command()
def cost(incident_ref: str = "INC-001", timeline: bool = False) -> None:
    """Show what one incident's latest run cost, and optionally its timeline."""
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    factory = build_session_factory(build_engine(settings))

    try:
        with session_scope(factory) as session:
            run_id = cost_reporting.latest_run_id(session, incident_ref)
            summary = summarise_run(session, run_id=run_id, incident_ref=incident_ref)
            lines = render_cost_summary(summary)
            events = incident_timeline(session, run_id=run_id) if timeline else []
            rendered = [
                f"  {event.occurred_at.isoformat()}  {event.source:<12} "
                f"{event.event_type:<28} {event.detail}"
                f"   trace={event.trace_id or '-'} span={event.span_id or '-'}"
                for event in events
            ]

        typer.echo(f"COST -- {incident_ref} (DEMO_MODE={settings.demo_mode})")
        for line in lines:
            typer.echo(line)
        typer.secho(f"  {CONCURRENCY_NOTE}", fg=typer.colors.YELLOW)

        if timeline:
            typer.echo(f"\nTIMELINE ({len(rendered)} events)")
            for line in rendered:
                typer.echo(line)
    except RevenueSentinelError as error:
        typer.secho(f"error: {error}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from error


# ---------------------------------------------------------------------------
# Reconciling an uncertain effect (ADR-0025)
# ---------------------------------------------------------------------------
RECONCILE_CAVEAT = (
    "Execution is at-least-once with an explicit unknown (ADR-0017). This records what "
    "a person attests happened; it does not make delivery exactly-once."
)


@app.command()
def actions(status: str = "indeterminate") -> None:
    """List actions awaiting human reconciliation.

    Only `indeterminate` is listed: it is the one status that requires a person, which
    is the whole reason this command exists.
    """
    if status != "indeterminate":
        typer.secho(
            "only --status indeterminate is supported; other statuses need no decision",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    factory = build_session_factory(build_engine(settings))

    with session_scope(factory) as session:
        rows = reconciliation.list_uncertain(session)

        if not rows:
            typer.echo("No indeterminate actions. Nothing is waiting on a person.")
            return

        typer.echo(f"{len(rows)} action(s) whose outcome is unknown:")
        for row in rows:
            typer.echo(f"  {row.action_record_id}  {row.action_type}  {row.incident_ref}")
            typer.echo(f"      target {row.target_ref} -- {row.integration_status}")
            typer.echo(f"      attempts {row.attempt_count}, claimed {row.claimed_at}")
            typer.echo(f"      inspect: uv run rs action {row.action_record_id}")
        typer.secho(f"\n{RECONCILE_CAVEAT}", fg=typer.colors.YELLOW)


@app.command()
def action(action_record_id: str) -> None:
    """Everything an operator needs to decide whether one uncertain effect happened."""
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    factory = build_session_factory(build_engine(settings))

    try:
        with session_scope(factory) as session:
            record = reconciliation.get_action(session, UUID(action_record_id))

            typer.echo(f"action        {record.id}")
            typer.echo(f"type          {record.action_type.value}")
            typer.echo(f"status        {record.status.value}")
            typer.echo(f"target        {record.target_ref}")
            typer.echo(f"attempts      {record.attempt_count}")
            typer.echo(f"idempotency   {record.idempotency_key}")
            typer.echo(f"authorized by policy evaluation {record.authorized_by}")
            typer.echo(f"approval      {record.approval_request_id or 'none (Tier 1)'}")
            typer.echo(f"result        {record.result or 'none recorded'}")

            if record.reconciled_by is not None:
                typer.echo(f"\nreconciled by {record.reconciled_by} at {record.reconciled_at}")
                typer.echo(f"evidence      {record.reconciliation_evidence}")
                return

            if record.status is not ActionStatus.INDETERMINATE:
                return

            typer.secho(
                "\nThe outcome of this effect is unknown. The process claimed it and "
                "died before recording what happened, so it may or may not have occurred.",
                fg=typer.colors.YELLOW,
            )
            typer.echo(
                "\nCheck the target system for evidence, then record what you found:\n"
                f"  uv run rs reconcile {record.id} --outcome occurred "
                "--as usr:your-name --evidence '<what you saw>'\n"
                f"  uv run rs reconcile {record.id} --outcome did-not-occur "
                "--as usr:your-name --evidence '<what you searched, and found nothing>'"
            )
            typer.echo(
                "\nThere is deliberately no retry command. A retry becomes possible only "
                "after somebody attests the effect did not occur (ADR-0025)."
            )
            typer.secho(f"\n{RECONCILE_CAVEAT}", fg=typer.colors.YELLOW)
    except (reconciliation.ReconciliationError, ValueError) as error:
        typer.secho(f"error: {error}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from error


@app.command()
def reconcile(
    action_record_id: str,
    # `Annotated` rather than a call in the default: ruff's B008 exempts plain `str`
    # defaults but not an enum, and requiredness reads better as "no default" anyway.
    outcome: Annotated[reconciliation.Outcome, typer.Option("--outcome")],
    actor: Annotated[str, typer.Option("--as")],
    evidence: Annotated[str, typer.Option("--evidence")],
) -> None:
    """Record what a person found about an uncertain effect.

    `--evidence` is mandatory: this system cannot verify what you saw in an external
    system, so the least it can do is require you to state it. `--as` is a claimed
    identity, not an authenticated one (ADR-0018).
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    factory = build_session_factory(build_engine(settings))

    try:
        with session_scope(factory) as session:
            record = reconciliation.reconcile(
                session,
                action_record_id=UUID(action_record_id),
                outcome=outcome,
                actor=actor,
                evidence=evidence,
                occurred_at=settings.evaluation_timestamp,
            )
            resolved = record.status.value
            key = record.idempotency_key
    except (reconciliation.ReconciliationError, ValueError) as error:
        typer.secho(f"error: {error}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from error

    typer.echo(f"{action_record_id} reconciled to {resolved} by {actor}")
    typer.echo(f"idempotency key unchanged: {key}")
    typer.secho(IDENTITY_WARNING, fg=typer.colors.YELLOW)
    typer.secho(RECONCILE_CAVEAT, fg=typer.colors.YELLOW)
