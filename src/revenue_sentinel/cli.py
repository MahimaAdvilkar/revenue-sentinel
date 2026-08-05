"""Command-line entry point.

Exposed as the `revenue-sentinel` console script. `scripts/seed.py` is a thin shim
over `seed` so the documented `make seed` target and this CLI cannot drift apart.
"""

from __future__ import annotations

import typer

from revenue_sentinel.core.config import get_settings
from revenue_sentinel.core.errors import RevenueSentinelError
from revenue_sentinel.core.logging import configure_logging
from revenue_sentinel.db.seeding import seed_database
from revenue_sentinel.db.session import build_engine, build_session_factory, session_scope
from revenue_sentinel.events.pipeline import run_ingestion_cycle
from revenue_sentinel.orchestration.runner import run_investigation

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
    except RevenueSentinelError as error:
        # Our own errors are expected conditions with actionable messages. A traceback
        # would bury the message that explains what to do next.
        typer.secho(f"error: {error}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from error


if __name__ == "__main__":  # pragma: no cover -- exercised via the console script
    app()
