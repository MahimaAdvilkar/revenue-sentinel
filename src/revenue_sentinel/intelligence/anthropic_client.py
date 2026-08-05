"""`AnthropicLLMClient` -- the live path.

> **Never executed in Session 3.** It is written, type-checked, and unit-tested
> against a stubbed SDK, but no live call has been made and no fixture was recorded
> from it. See ADR-0013 and `PROJECT_STATUS.md`.

`anthropic` is imported inside `__init__`, not at module scope, so importing this
module in fixture mode does not load the SDK. A test asserts `anthropic` is absent
from `sys.modules` after a full offline run.

Structured output is obtained through a single forced tool call rather than by asking
for JSON in prose: the model must call the tool, and the tool's `input_schema` is the
Pydantic schema. That removes the "parse the response" step entirely -- there is no
free text to parse (rule 4).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final, cast

from pydantic import BaseModel, ValidationError

from revenue_sentinel.core.errors import ConfigurationError, StructuredOutputError
from revenue_sentinel.intelligence.digest import prompt_digest
from revenue_sentinel.intelligence.ports import LLMRequest, LLMResponse

if TYPE_CHECKING:
    from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam
    from anthropic.types.tool_param import InputSchema as InputSchemaLike
    from pydantic import SecretStr

STRUCTURED_TOOL_NAME: Final = "emit_structured_output"
MAX_OUTPUT_TOKENS: Final = 4096


class AnthropicLLMClient:
    """Calls the Claude API. Requires a key and network; costs money."""

    def __init__(self, api_key: SecretStr, *, max_output_tokens: int = MAX_OUTPUT_TOKENS) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover -- declared dependency
            raise ConfigurationError(
                "the `anthropic` package is required for live or record mode"
            ) from exc

        self._client = Anthropic(api_key=api_key.get_secret_value())
        self._max_output_tokens = max_output_tokens

    def complete_structured[T: BaseModel](self, request: LLMRequest[T]) -> LLMResponse[T]:
        digest = prompt_digest(request)

        # Structured output via a forced tool call rather than "please reply in JSON".
        # The tool's input_schema *is* the Pydantic schema, so there is no free text
        # to parse and no parsing step to get wrong (rule 4).
        tool: ToolParam = {
            "name": STRUCTURED_TOOL_NAME,
            "description": f"Emit a {request.output_schema.__name__}.",
            "input_schema": cast("InputSchemaLike", request.output_schema.model_json_schema()),
        }
        tool_choice: ToolChoiceToolParam = {"type": "tool", "name": STRUCTURED_TOOL_NAME}
        messages: list[MessageParam] = [{"role": "user", "content": request.user_content}]

        started = time.perf_counter()
        message = self._client.messages.create(
            model=request.model_id,
            max_tokens=self._max_output_tokens,
            system=request.system_prompt,
            messages=messages,
            tools=[tool],
            tool_choice=tool_choice,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        # Narrowed on the discriminator rather than duck-typed: the content union has
        # a dozen members and only `tool_use` carries `.input`.
        payload: object | None = None
        for block in message.content:
            if block.type == "tool_use" and block.name == STRUCTURED_TOOL_NAME:
                payload = block.input
                break
        if payload is None:
            raise StructuredOutputError(
                f"{request.node_name}: the model returned no {STRUCTURED_TOOL_NAME} call"
            )

        try:
            output = request.output_schema.model_validate(payload)
        except ValidationError as exc:
            raise StructuredOutputError(
                f"{request.node_name}: output does not satisfy "
                f"{request.output_schema.__name__}: {exc}"
            ) from exc

        return LLMResponse(
            output=output,
            model_id=message.model,
            effort=request.effort,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            latency_ms=latency_ms,
            stop_reason=message.stop_reason or "unknown",
            is_replay=False,
            prompt_digest=digest,
        )
