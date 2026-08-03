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


if __name__ == "__main__":  # pragma: no cover -- exercised via the console script
    app()
