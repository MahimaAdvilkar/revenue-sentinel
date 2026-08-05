"""Binding an `LLMClient` to the configured demo mode.

This is the only place that decides which implementation runs, and it is a total
function over `DEMO_MODE`: `fixture` replays, `live` and `record` call the API. There
is no branch in which `fixture` reaches the network (ADR-0007).

The `anthropic_client` module is imported inside the live branch so that fixture mode
never loads the SDK at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from revenue_sentinel.core.config import FIXTURES_DIR, Settings
from revenue_sentinel.core.errors import ConfigurationError
from revenue_sentinel.intelligence.fixture_client import FixtureLLMClient
from revenue_sentinel.intelligence.ports import LLMClient

LLM_FIXTURE_DIR: Final[Path] = FIXTURES_DIR / "llm"


def build_llm_client(settings: Settings, *, fixture_dir: Path | None = None) -> LLMClient:
    """Return the client the configured mode calls for.

    Raises:
        ConfigurationError: if a billable mode is selected without an API key. The
            `Settings` validator already enforces this at startup; the check is
            repeated here because this function is also called directly in tests, and
            a guard that only runs in one path is a guard with a gap.
    """
    if settings.demo_mode == "fixture":
        return FixtureLLMClient(fixture_dir or LLM_FIXTURE_DIR)

    if settings.anthropic_api_key is None:
        raise ConfigurationError(
            f"DEMO_MODE={settings.demo_mode} requires ANTHROPIC_API_KEY. "
            f"Fixture mode does not fall back to a live call, and a live mode does "
            f"not start without its credential."
        )

    from revenue_sentinel.intelligence.anthropic_client import AnthropicLLMClient

    return AnthropicLLMClient(settings.anthropic_api_key)
