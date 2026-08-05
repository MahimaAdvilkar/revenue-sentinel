"""The LLM client port.

One protocol, two implementations, and **no call site knows which is bound**
(ADR-0007). That is what lets the demo, the tests, and CI run offline while the same
code path works against the real API.

`complete_structured` is the only method. There is no `complete_text`, deliberately:
a free-text entry point is how "just parse the response" gets written, and rule 4
says LLM calls return validated structured output or nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class LLMRequest[T: BaseModel]:
    """One structured-output request.

    `system_prompt` is a frozen constant chosen by the call site. `user_content`
    carries the untrusted, delimited evidence. Keeping them separate fields rather
    than one concatenated string is what makes "ingested content never enters the
    system prompt" checkable (rule 14).
    """

    node_name: str
    system_prompt: str
    user_content: str
    output_schema: type[T]
    model_id: str
    effort: str


@dataclass(frozen=True, slots=True)
class LLMResponse[T: BaseModel]:
    """A validated response, plus what it cost.

    `is_replay` is `True` when this came from a fixture. In that case the token
    counts are **zero, because zero were consumed** -- they are not estimates, and
    they are not copied from whatever the model once returned. See ADR-0013.
    """

    output: T
    model_id: str
    effort: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    stop_reason: str
    is_replay: bool
    prompt_digest: str


@runtime_checkable
class LLMClient(Protocol):
    """A source of schema-validated model output."""

    def complete_structured[T: BaseModel](self, request: LLMRequest[T]) -> LLMResponse[T]:
        """Return validated output, or raise. Never returns unvalidated text."""
        ...
