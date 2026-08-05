"""`make investigate INCIDENT=INC-001` -- run the investigation graph.

A shim over `revenue_sentinel.cli.investigate` so the Makefile target and the console
script run identical code.
"""

from __future__ import annotations

import sys

from revenue_sentinel.cli import investigate

if __name__ == "__main__":
    investigate(sys.argv[1] if len(sys.argv) > 1 else "INC-001")
