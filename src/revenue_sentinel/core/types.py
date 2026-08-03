"""Shared type aliases.

`JSONValue` is the only sanctioned way to type a JSONB payload. It exists so that
`domain/` and `analytics/` can describe schemaless columns without `Any` --
`pyproject.toml` sets `disallow_any_explicit` for those modules, so `dict[str, Any]`
is not available to them and this alias is what they use instead.
"""

from __future__ import annotations

type JSONValue = str | int | float | bool | list[JSONValue] | dict[str, JSONValue] | None
"""Anything that survives a JSON round trip, recursively."""

type JSONObject = dict[str, JSONValue]
"""A JSON object at the top level -- the shape of every JSONB column we define."""
