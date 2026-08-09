"""Write the FastAPI OpenAPI schema to `apps/web/generated/openapi.json`.

The schema is the frontend/backend contract (ADR-0023), so it is **checked in**: a
reviewer can see a contract change in the diff, and the frontend builds without needing
a running API.

Deterministic by construction -- keys sorted, fixed indentation -- so regenerating
without a backend change produces no diff.

**Exporting the schema does not read runtime configuration.** The document is a pure
function of the route and model definitions: no setting appears anywhere in it. Calling
`get_settings()` here made the export depend on a configured `DATABASE_URL` that it never
connects to, which broke the CI job whose whole point is that it needs no database --
and gave anyone running this from a fresh clone a pydantic validation error about a
database they were not trying to reach.

So the settings below are constructed explicitly, with the `.env` file disabled and the
values that matter pinned. The placeholder URL is never connected to: SQLAlchemy's
`create_engine` is lazy, and this process only asks the app for its schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from revenue_sentinel.api.main import create_app
from revenue_sentinel.core.config import Settings
from revenue_sentinel.core.types import JSONObject

TARGET: Final = Path("apps/web/generated/openapi.json")

UNUSED_DATABASE_URL: Final = "postgresql+psycopg://schema-export@localhost/unused"
"""Satisfies `Settings`; never connected to.

`create_engine` does not open a connection, and generating an OpenAPI document does not
touch the database. A real URL here would imply this step reaches one.
"""


def schema_settings() -> Settings:
    """Configuration for schema export, independent of the environment.

    `_env_file=None` and the pinned values keep the emitted document identical on a
    developer machine, in a fresh clone, and on a CI runner with nothing configured.
    """
    return Settings(
        _env_file=None,
        database_url=UNUSED_DATABASE_URL,
        demo_mode="fixture",
    )


def build_schema() -> JSONObject:
    """The OpenAPI document, as a plain dict."""
    return create_app(settings=schema_settings()).openapi()


def render(schema: JSONObject) -> str:
    """Sorted keys and fixed indentation, so regeneration is byte-stable."""
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    schema = build_schema()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(schema), encoding="utf-8")
    print(f"wrote {TARGET} ({len(schema['paths'])} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
