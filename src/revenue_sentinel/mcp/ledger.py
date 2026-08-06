"""The tool-call ledger.

Every invocation writes a row -- success, error, **and denial**. A refused call is the
most interesting kind to have a record of, and the easiest to forget to write.

Arguments are stored; results are digested. Storing results would duplicate
`evidence_items` and grow without bound, while the digest is enough to prove two calls
returned the same thing.

Span ids derive from `(run_id, node, tool, ordinal)` so a replayed run traces
identically -- the same property Session 3 established for model calls.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from revenue_sentinel.core.ids import new_id
from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import observability as orm
from revenue_sentinel.domain.enums import ToolCallStatus

TRACE_ID_LENGTH: Final = 32
SPAN_ID_LENGTH: Final = 16


def _hex_id(*parts: str, length: int) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:length]


def digest_of(payload: JSONObject) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_tool_call(
    session: Session,
    *,
    run_id: UUID,
    node_name: str,
    tool_name: str,
    arguments: JSONObject,
    result: JSONObject,
    status: ToolCallStatus,
    duration_ms: int,
    ordinal: int,
) -> orm.ToolCall:
    """Write one `tool_calls` row."""
    row = orm.ToolCall(
        id=new_id(),
        run_id=run_id,
        node_name=node_name,
        tool_name=tool_name,
        args=arguments,
        result_digest=digest_of(result),
        status=status,
        duration_ms=duration_ms,
        trace_id=_hex_id(str(run_id), length=TRACE_ID_LENGTH),
        span_id=_hex_id(str(run_id), node_name, tool_name, str(ordinal), length=SPAN_ID_LENGTH),
        parent_span_id=_hex_id(str(run_id), node_name, length=SPAN_ID_LENGTH),
    )
    session.add(row)
    session.flush()
    return row
