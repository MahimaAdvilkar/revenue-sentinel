"""Prompt digests.

Fixtures are keyed by a hash over everything that could change the response: the
model, the effort level, both halves of the prompt, and the output schema.

The schema is included on purpose. A response recorded against an older schema would
still deserialize if the change was additive, and would then be silently wrong --
tested against yesterday's contract. Including the schema in the key turns that into
a fixture miss, which is loud.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel

    from revenue_sentinel.intelligence.ports import LLMRequest


def schema_fingerprint(schema: type[BaseModel]) -> str:
    """A stable fingerprint of a Pydantic model's JSON schema."""
    return json.dumps(schema.model_json_schema(), sort_keys=True, separators=(",", ":"))


def prompt_digest(request: LLMRequest[BaseModel]) -> str:
    """`sha256` over model, effort, system prompt, user content, and schema.

    Field order is fixed and each part is length-prefixed, so no combination of
    contents can collide with a different combination by running together.
    """
    parts = (
        request.model_id,
        request.effort,
        request.system_prompt,
        request.user_content,
        schema_fingerprint(request.output_schema),
    )
    hasher = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        hasher.update(str(len(encoded)).encode("ascii"))
        hasher.update(b"\x00")
        hasher.update(encoded)
    return hasher.hexdigest()
