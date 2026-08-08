"""A deterministic, conservative input-token estimate for admission control.

**This is not billing truth and must never be treated as usage.** It exists to answer one
question before a call is made: *could this call possibly exceed a budget?* The provider's
tokenizer is authoritative and differs from this; only actual usage returned by the
provider is ever written to `model_calls`.

Three properties matter more than accuracy:

* **Deterministic.** Same request, same estimate, on every machine. A replayed run must
  make the same admission decision as the run it replays.
* **Never intentionally low.** Under-estimating admits a call that should have been
  refused, which is the failure this whole layer exists to prevent. The divisor and the
  overhead below are chosen to over-count.
* **Separately testable.** No database, no client, no request object beyond strings.

The estimator counts the system prompt, the user content, and the JSON Schema that is
transmitted with a structured-output request -- omitting the schema would under-count by
exactly the amount most likely to be large.
"""

from __future__ import annotations

import json
from typing import Final

from pydantic import BaseModel

ESTIMATOR_VERSION: Final = "estimator/v1-chars"

CHARS_PER_TOKEN: Final = 3
"""Deliberately below the ~4 characters-per-token rule of thumb for English.

A lower divisor yields a **higher** token count, which is the direction that fails safe:
this over-estimates rather than under-estimates. Real tokenizers do better than 3 on
prose and worse on JSON and identifiers, and this content is full of both."""

MESSAGE_OVERHEAD_TOKENS: Final = 16
"""Role markers, message framing, and the tool/schema wrapper the provider adds. A flat
conservative constant beats a precise model of a format that is not ours to depend on."""


def estimate_tokens(text: str) -> int:
    """Characters to tokens, rounding **up**."""
    if not text:
        return 0
    return -(-len(text) // CHARS_PER_TOKEN)


def schema_overhead(output_schema: type[BaseModel]) -> int:
    """The JSON Schema is sent to the provider, so it is charged as input.

    Ignoring it would under-count by the single largest structured component of the
    request -- `InterventionSet`'s schema is not small.
    """
    return estimate_tokens(json.dumps(output_schema.model_json_schema(), sort_keys=True))


def estimate_input_tokens(
    *, system_prompt: str, user_content: str, output_schema: type[BaseModel]
) -> int:
    """The conservative input-token count used for admission control only."""
    return (
        estimate_tokens(system_prompt)
        + estimate_tokens(user_content)
        + schema_overhead(output_schema)
        + MESSAGE_OVERHEAD_TOKENS
    )
