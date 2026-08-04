"""`make ingest` -- run one ingestion cycle over the SIMULATED source feed.

A shim over `revenue_sentinel.cli.ingest` so the Makefile target and the console
script run identical code.
"""

from __future__ import annotations

from revenue_sentinel.cli import ingest

if __name__ == "__main__":
    ingest()
