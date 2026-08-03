# ADR-0010: "Zero `Any`" is enforced by an AST check, not by `disallow_any_explicit`

**Status:** Accepted
**Date:** 2026-08-02
**Deciders:** Mahima Advilkar

## Context

Session 1 acceptance criterion 4 requires that domain models are "Pydantic v2 with zero
`Any`", and Phase 1 encoded that in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = ["revenue_sentinel.domain.*", "revenue_sentinel.analytics.*"]
disallow_any_explicit = true
```

That configuration was written before any model existed. The first model made it fail, and
so did every model after it — 29 errors, all pointing at the `class` line:

```
src/revenue_sentinel/domain/gtm.py:46: error: Explicit "Any" is not allowed  [explicit-any]
```

Reduced to a three-line file, the cause is unambiguous: the pydantic mypy plugin synthesises
an `Any`-typed `__init__` for every `BaseModel` subclass, and `disallow_any_explicit`
attributes that synthesised code to the module that declared the class. A plain (non-model)
class in the same file produces no error.

The flag was therefore unsatisfiable by construction. It measured the plugin, not our code.

Rule 13 forbids weakening a gate to get green, so "delete the flag" needed to be more than a
convenience — the *intent* had to end up better enforced, not merely differently enforced.

## Decision

**Remove `disallow_any_explicit` and enforce the intent with
[`../../tests/unit/test_no_any_in_pure_layers.py`](../../tests/unit/test_no_any_in_pure_layers.py),
which walks the AST of `domain/` and `analytics/` and fails on any reference to `Any`.**

The check flags four forms:

- a bare `Any` name,
- an attribute access ending in `.Any` (`typing.Any`, `t.Any`),
- `from typing import Any`,
- `Any` appearing inside a string annotation, which it finds by re-parsing string constants.

It also asserts that the scan found at least eight source files, so it cannot pass by
silently scanning nothing — the failure mode that makes a green check worthless.

`strict = true` remains in force for the entire `src/` tree, including these packages. Only
the `explicit-any` sub-flag is gone.

## Alternatives considered

**Keep the flag and add `# type: ignore[explicit-any]` to every model.** Rejected: 29
suppressions of a real error code, which would also hide a genuine `Any` written by hand.
That is the silencing rule 13 prohibits.

**Keep the flag and drop the pydantic mypy plugin.** Rejected: the plugin is what gives
required-field checking on model construction. Trading real type safety for a flag that
checks the wrong thing is a bad exchange.

**Drop the requirement and rely on `strict = true`.** Rejected: `strict` prohibits *implicit*
`Any` but permits an explicit one, so `dict[str, Any]` would pass. That is exactly the
construct
[`../../src/revenue_sentinel/core/types.py`](../../src/revenue_sentinel/core/types.py)
exists to replace with `JSONObject`.

## Consequences

**Easier:** the check is strictly stronger than the flag it replaces — it catches `Any`
inside string annotations and `cast(Any, ...)`, neither of which `disallow_any_explicit`
reports. It runs in the normal test suite, so a developer sees it in seconds rather than in
CI. And the rule is now readable as code instead of as a config key whose semantics have to
be looked up.

**Harder:** it is a custom check rather than a standard tool, so it needs maintaining. It is
also syntactic — it would not catch `Any` reaching these packages through an untyped
third-party import. `strict = true` covers that case.

**We now owe:** the check must stay pointed at the right packages. If a new pure layer is
added, `PURE_PACKAGES` has to include it, or the boundary silently stops being checked.

## Revisit when

Either the pydantic mypy plugin stops synthesising `Any`-typed `__init__` methods, or mypy
grows a way to scope `disallow_any_explicit` to hand-written annotations only. At that point
the standard tool does the job and the custom check should be deleted rather than kept
alongside it.
