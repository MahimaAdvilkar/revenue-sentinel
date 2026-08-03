"""Acceptance criterion 8: all six import-linter contracts hold.

Asserted by the test suite as well as by CI. A boundary that is only checked in CI
is a boundary a developer discovers they have broken twenty minutes after they broke
it, by which time the offending import feels load-bearing.

These contracts are honest but not yet fully exercised: several of the forbidden
packages are still empty in Session 1, so some contracts pass partly by default.
They gain teeth as Sessions 2-6 fill those packages in. R3 -- `analytics/` cannot
import `intelligence/` or `agents/` -- is real today, because `analytics/` has
content.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from revenue_sentinel.core.config import PROJECT_ROOT

EXPECTED_CONTRACTS = 6


def test_all_import_linter_contracts_are_kept() -> None:
    # The `lint-imports` console script is what the Makefile and CI run. Invoking
    # the same entry point here means this test cannot pass while `make boundaries`
    # fails.
    executable = Path(sys.executable).parent / "lint-imports"
    assert executable.is_file(), f"lint-imports not installed at {executable}"

    result = subprocess.run(  # noqa: S603 -- fixed argv, no shell, no user input
        [str(executable)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"import-linter reported a broken contract:\n{result.stdout}"
    assert f"Contracts: {EXPECTED_CONTRACTS} kept, 0 broken." in result.stdout


def test_analytics_never_imports_the_model_layer() -> None:
    """R3, read straight out of the source rather than only via the linter.

    This is the contract the demo makes a claim about out loud: the model cannot
    reach the money math. Checked here by inspecting every import statement in
    `analytics/`, so the claim is verified against the code rather than against a
    tool's summary line.
    """
    forbidden = ("revenue_sentinel.intelligence", "revenue_sentinel.agents")
    analytics = PROJECT_ROOT / "src" / "revenue_sentinel" / "analytics"
    modules = sorted(analytics.rglob("*.py"))
    assert modules, "analytics/ has no modules to check"

    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden), (
                    f"{path.name}:{node.lineno} imports {node.module}"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden), (
                        f"{path.name}:{node.lineno} imports {alias.name}"
                    )
