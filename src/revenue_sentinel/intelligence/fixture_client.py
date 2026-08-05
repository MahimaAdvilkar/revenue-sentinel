"""`FixtureLLMClient` -- replay only.

This class holds no API key, no HTTP client, and no import of `anthropic`. **There is
no fallback branch.** A fallback is not disabled here; it does not exist, which is a
stronger guarantee than a flag that could be flipped (ADR-0007).

Token counts on a replayed response are **zero, because zero were consumed**. They
are not estimates and they are not copied from a past live call. `is_replay` and
`stop_reason="fixture_replay"` say plainly what happened, and the same facts are
carried into `model_calls` so the ledger cannot imply a call that never occurred.
See ADR-0013.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ValidationError

from revenue_sentinel.core.errors import FixtureMissError, StructuredOutputError
from revenue_sentinel.intelligence.digest import prompt_digest
from revenue_sentinel.intelligence.ports import LLMRequest, LLMResponse

FIXTURE_STOP_REASON: Final = "fixture_replay"
DIGEST_FILENAME_LENGTH: Final = 12


def fixture_filename(node_name: str, digest: str) -> str:
    """`plan_investigation.6f1c2a9b4e77.json`.

    The node name leads so a directory listing is readable by a human; the truncated
    digest disambiguates. The full digest is stored inside the file and verified on
    load, so the short prefix is a filename convenience and never the identity.
    """
    return f"{node_name}.{digest[:DIGEST_FILENAME_LENGTH]}.json"


class FixtureLLMClient:
    """Replays recorded responses. Never reaches the network."""

    def __init__(self, fixture_dir: Path) -> None:
        self._fixture_dir = fixture_dir

    def complete_structured[T: BaseModel](self, request: LLMRequest[T]) -> LLMResponse[T]:
        digest = prompt_digest(request)
        path = self._fixture_dir / fixture_filename(request.node_name, digest)

        if not path.is_file():
            raise FixtureMissError(request.node_name, digest, str(path))

        payload = json.loads(path.read_text(encoding="utf-8"))
        recorded_digest = payload.get("prompt_digest")
        if recorded_digest != digest:
            raise StructuredOutputError(
                f"fixture {path.name} records digest {recorded_digest}, "
                f"but the current prompt digests to {digest}. The prompt or schema "
                f"changed; regenerate the fixture."
            )

        try:
            output = request.output_schema.model_validate(payload["output"])
        except (ValidationError, KeyError) as exc:
            raise StructuredOutputError(
                f"fixture {path.name} does not satisfy {request.output_schema.__name__}: {exc}"
            ) from exc

        return LLMResponse(
            output=output,
            model_id=request.model_id,
            effort=request.effort,
            # Zero, because zero were consumed. Not an estimate.
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            stop_reason=FIXTURE_STOP_REASON,
            is_replay=True,
            prompt_digest=digest,
        )
