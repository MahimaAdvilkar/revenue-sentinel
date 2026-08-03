"""Acceptance criterion 4: zero `Any` in `domain/` and `analytics/`.

Phase 1 declared `disallow_any_explicit` in `pyproject.toml` for these packages, but
that flag cannot be satisfied by any Pydantic model: the pydantic mypy plugin
synthesises an `Any`-typed `__init__`, so it fires on the `class` line regardless of
what we write. It measured the plugin, not our code. See ADR-0010.

This check enforces the actual intent by walking the AST, and it is strictly
stronger than the flag was: it also catches `Any` hidden inside string annotations
and `cast(Any, ...)`, neither of which the mypy flag reports.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from revenue_sentinel.core.config import PROJECT_ROOT

PURE_PACKAGES = ("domain", "analytics")


def _pure_source_files() -> list[Path]:
    root = PROJECT_ROOT / "src" / "revenue_sentinel"
    return sorted(path for package in PURE_PACKAGES for path in (root / package).rglob("*.py"))


def _any_references(tree: ast.AST) -> list[str]:
    """Every syntactic reference to `Any`, including inside string annotations."""
    found: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "Any":
            found.append(f"line {node.lineno}: bare name `Any`")
        elif isinstance(node, ast.Attribute) and node.attr == "Any":
            found.append(f"line {node.lineno}: attribute `.Any`")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "Any":
                    found.append(f"line {node.lineno}: `from {node.module} import Any`")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # String annotations are still annotations.
            try:
                inner = ast.parse(node.value, mode="eval")
            except SyntaxError:
                continue
            for sub in ast.walk(inner):
                if isinstance(sub, ast.Name) and sub.id == "Any":
                    found.append(f"line {node.lineno}: `Any` inside a string annotation")

    return found


def test_the_pure_layers_actually_contain_source_files() -> None:
    """Guard against the check passing because it scanned nothing."""
    files = _pure_source_files()
    assert len(files) >= 8, f"expected the pure packages to hold modules, found {files}"


@pytest.mark.parametrize("path", _pure_source_files(), ids=lambda p: p.name)
def test_no_any_in_pure_layer_module(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations = _any_references(tree)
    assert not violations, f"{path.relative_to(PROJECT_ROOT)} uses Any:\n  " + "\n  ".join(
        violations
    )
