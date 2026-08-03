"""`make seed` -- load the deterministic synthetic data set.

A shim over `revenue_sentinel.cli.seed` so the Makefile target and the console
script run identical code.
"""

from __future__ import annotations

from revenue_sentinel.cli import seed

if __name__ == "__main__":
    seed()
