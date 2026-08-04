"""Command-line entry point.

Exposed as the `revenue-sentinel` console script. `scripts/seed.py` is a thin shim
over `seed` so the documented `make seed` target and this CLI cannot drift apart.
"""

from __future__ import annotations

import typer

from revenue_sentinel.core.config import get_settings
from revenue_sentinel.core.logging import configure_logging
from revenue_sentinel.db.seeding import seed_database
from revenue_sentinel.db.session import build_engine, build_session_factory, session_scope
from revenue_sentinel.events.pipeline import run_ingestion_cycle

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


if __name__ == "__main__":  # pragma: no cover -- exercised via the console script
    app()
