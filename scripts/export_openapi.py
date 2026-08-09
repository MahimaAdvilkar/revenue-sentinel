"""Write the FastAPI OpenAPI schema to `apps/web/generated/openapi.json`.

The schema is the frontend/backend contract (ADR-0023), so it is **checked in**: a
reviewer can see a contract change in the diff, and the frontend builds without needing
a running API.

Deterministic by construction -- keys sorted, fixed indentation -- so regenerating
without a backend change produces no diff.
"""

from __future__ import annotations

import json
from pathlib import Path

from revenue_sentinel.api.main import create_app
from revenue_sentinel.core.config import get_settings

TARGET = Path("apps/web/generated/openapi.json")


def main() -> int:
    schema = create_app(settings=get_settings()).openapi()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {TARGET} ({len(schema['paths'])} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
