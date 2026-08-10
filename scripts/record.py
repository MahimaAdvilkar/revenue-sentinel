"""Re-record the LLM fixtures against the live API. **Never run in this project.**

`make record` has pointed here since Session 3 and this module did not exist, so anyone
following ADR-0013's instructions got `ModuleNotFoundError`. That is now fixed: the
escape hatch is real, guarded, and still unused.

**This is the only code path in the repository that spends money.** It exists because
ADR-0013 accepted hand-authored fixtures as a bootstrap and named this as how they stop
being hand-authored. The project's claim -- *no live API call has ever been made* -- holds
only for as long as nobody runs it.

## Guards, in order

1. Refuses `DEMO_MODE=fixture`. Recording is an explicit mode, never a fallback.
2. Refuses without `ANTHROPIC_API_KEY`. `Settings` enforces this too; repeated here
   because a guard that runs in one path only is a guard with a gap.
3. Refuses without `--confirm`. The Makefile also prompts; belt and braces, because the
   failure mode is billing.
4. Prints exactly which call sites will be recorded, and what each replaces, *before*
   doing anything.

The key is never printed, logged, or written to a fixture -- only its presence is
reported.

## What it does

Runs the ordinary investigation graph with a recording wrapper around the live client.
The wrapper delegates, then writes the response to `fixtures/llm/<node>.<digest>.json`
using the same `prompt_digest` and `fixture_filename` helpers the replay client uses --
so a recorded fixture is loadable by construction rather than by convention.

Afterwards, run `make demo` and then `python -m scripts.check_fixtures --stamp` so the
template digests match the code the fixtures were recorded against (ADR-0024).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from revenue_sentinel.core.config import get_settings
from revenue_sentinel.core.errors import ConfigurationError
from revenue_sentinel.db.session import build_engine, build_session_factory, session_scope
from revenue_sentinel.intelligence.digest import prompt_digest
from revenue_sentinel.intelligence.factory import LLM_FIXTURE_DIR, build_llm_client
from revenue_sentinel.intelligence.fixture_client import fixture_filename
from revenue_sentinel.intelligence.ports import LLMClient, LLMRequest, LLMResponse
from revenue_sentinel.orchestration.runner import run_investigation
from scripts.check_fixtures import CALL_SITES

RECORDED_NOTE: Final = (
    "RECORDED from a live Anthropic API call by scripts/record.py. This replaces a "
    "hand-authored fixture; see ADR-0013."
)


class RecordingLLMClient:
    """Delegates to the live client and writes what came back.

    The filename and the recorded digest both come from `prompt_digest`, the same
    function the replay client verifies on load -- so a fixture written here cannot be
    one the replay client would refuse.
    """

    def __init__(self, inner: LLMClient, fixture_dir: Path) -> None:
        self._inner = inner
        self._fixture_dir = fixture_dir
        self.written: list[Path] = []

    def complete_structured[T: BaseModel](self, request: LLMRequest[T]) -> LLMResponse[T]:
        response = self._inner.complete_structured(request)
        digest = prompt_digest(request)
        path = self._fixture_dir / fixture_filename(request.node_name, digest)

        path.write_text(
            json.dumps(
                {
                    "$note": RECORDED_NOTE,
                    "node_name": request.node_name,
                    "prompt_digest": digest,
                    "output": response.output.model_dump(mode="json"),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        self.written.append(path)
        print(f"  recorded {path.name}")
        return response


def _refuse(reason: str) -> int:
    print(f"refusing to record: {reason}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-record LLM fixtures. Costs money.")
    parser.add_argument("--confirm", action="store_true", help="required; nothing runs without it")
    parser.add_argument("--incident", default="INC-001")
    args = parser.parse_args(argv)

    settings = get_settings()

    if settings.demo_mode == "fixture":
        return _refuse(
            "DEMO_MODE=fixture. Recording is an explicit mode, never a fallback from "
            "replay. Set DEMO_MODE=record."
        )
    if settings.anthropic_api_key is None:
        return _refuse("ANTHROPIC_API_KEY is not set. A live mode does not start without it.")

    print("This will make REAL, BILLABLE Anthropic API calls and overwrite fixtures.")
    print(f"  mode      {settings.demo_mode}")
    print("  api key   present (never printed)")
    print(f"  incident  {args.incident}")
    print(f"  directory {LLM_FIXTURE_DIR}")
    print(f"  call sites ({len(CALL_SITES)}):")
    for site in CALL_SITES:
        existing = sorted(LLM_FIXTURE_DIR.glob(f"{site.node_name}.*.json"))
        replaces = existing[0].name if existing else "nothing recorded yet"
        print(f"    - {site.node_name}: replaces {replaces}")

    if not args.confirm:
        return _refuse("--confirm was not passed. Nothing has been sent.")

    try:
        client = build_llm_client(settings)
    except ConfigurationError as error:
        return _refuse(str(error))

    recorder = RecordingLLMClient(client, LLM_FIXTURE_DIR)
    factory = build_session_factory(build_engine(settings))
    with session_scope(factory) as session:
        run_investigation(session, args.incident, settings=settings, llm=recorder)

    print(f"\nwrote {len(recorder.written)} fixture(s).")
    print("Now run `make demo`, then `python -m scripts.check_fixtures --stamp` (ADR-0024).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
