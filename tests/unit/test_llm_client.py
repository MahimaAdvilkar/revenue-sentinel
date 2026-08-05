"""The LLM port: digest, fixture replay, and client selection.

The load-bearing claim of ADR-0007 is that fixture mode **cannot** reach the network.
These tests hold it to that: a miss raises, the digest is sensitive to everything that
could change a response, and the fixture client has no code path to an API.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from revenue_sentinel.core.config import PROJECT_ROOT, Settings
from revenue_sentinel.core.errors import (
    ConfigurationError,
    FixtureMissError,
    StructuredOutputError,
)
from revenue_sentinel.intelligence.digest import prompt_digest, schema_fingerprint
from revenue_sentinel.intelligence.factory import build_llm_client
from revenue_sentinel.intelligence.fixture_client import (
    FIXTURE_STOP_REASON,
    FixtureLLMClient,
    fixture_filename,
)
from revenue_sentinel.intelligence.ports import LLMRequest

VALID_URL = "postgresql+psycopg://sentinel:local@localhost:55432/revenue_sentinel"


class Answer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    value: str


class OtherAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    value: int


def a_request(**overrides: object) -> LLMRequest[Answer]:
    payload: dict[str, object] = {
        "node_name": "some_node",
        "system_prompt": "system",
        "user_content": "<evidence>data</evidence>",
        "output_schema": Answer,
        "model_id": "claude-opus-5",
        "effort": "high",
    }
    payload.update(overrides)
    return LLMRequest(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------
def test_the_digest_is_stable() -> None:
    assert prompt_digest(a_request()) == prompt_digest(a_request())


@pytest.mark.parametrize(
    "change",
    [
        {"model_id": "claude-haiku-4-5"},
        {"effort": "low"},
        {"system_prompt": "different"},
        {"user_content": "different"},
        {"output_schema": OtherAnswer},
    ],
)
def test_the_digest_changes_with_anything_that_could_change_the_response(
    change: dict[str, object],
) -> None:
    assert prompt_digest(a_request()) != prompt_digest(a_request(**change))


def test_the_schema_is_part_of_the_key() -> None:
    """A response recorded against an older schema would still deserialize if the
    change was additive, and would then be silently wrong. Including the schema turns
    that into a fixture miss, which is loud."""
    assert schema_fingerprint(Answer) != schema_fingerprint(OtherAnswer)


def test_length_prefixing_prevents_field_collisions() -> None:
    """Without length prefixes, ("ab", "c") and ("a", "bc") would digest identically."""
    first = a_request(system_prompt="ab", user_content="c")
    second = a_request(system_prompt="a", user_content="bc")
    assert prompt_digest(first) != prompt_digest(second)


def test_the_filename_leads_with_the_node_name() -> None:
    """So a directory listing is readable by a human."""
    name = fixture_filename("plan_investigation", "a" * 64)
    assert name == "plan_investigation." + "a" * 12 + ".json"


# ---------------------------------------------------------------------------
# Fixture replay
# ---------------------------------------------------------------------------
def write_fixture(directory: Path, request: LLMRequest[Answer], output: object) -> Path:
    digest = prompt_digest(request)
    path = directory / fixture_filename(request.node_name, digest)
    path.write_text(json.dumps({"prompt_digest": digest, "output": output}), encoding="utf-8")
    return path


def test_a_recorded_response_is_replayed(tmp_path: Path) -> None:
    request = a_request()
    write_fixture(tmp_path, request, {"value": "recorded"})

    response = FixtureLLMClient(tmp_path).complete_structured(request)

    assert response.output.value == "recorded"
    assert isinstance(response.output, Answer)


def test_a_replayed_response_reports_zero_tokens(tmp_path: Path) -> None:
    """Zero because zero were consumed -- not an estimate, not copied. ADR-0013."""
    request = a_request()
    write_fixture(tmp_path, request, {"value": "recorded"})

    response = FixtureLLMClient(tmp_path).complete_structured(request)

    assert response.is_replay is True
    assert response.input_tokens == 0
    assert response.output_tokens == 0
    assert response.latency_ms == 0
    assert response.stop_reason == FIXTURE_STOP_REASON


def test_a_miss_raises_and_names_the_file_it_wanted(tmp_path: Path) -> None:
    request = a_request()

    with pytest.raises(FixtureMissError) as caught:
        FixtureLLMClient(tmp_path).complete_structured(request)

    assert caught.value.node_name == "some_node"
    assert caught.value.digest == prompt_digest(request)
    assert "some_node" in caught.value.expected_path
    assert "does not fall back" in str(caught.value)


def test_the_fixture_client_imports_nothing_that_could_reach_a_network() -> None:
    """A fallback is not disabled here -- it does not exist.

    Checked against the module's imports rather than its text: the docstring names
    `anthropic` while explaining that it is never imported, and a substring search
    would flag exactly the sentence that documents the guarantee.
    """
    module = PROJECT_ROOT / "src" / "revenue_sentinel" / "intelligence" / "fixture_client.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {"anthropic", "httpx", "requests", "urllib", "socket", "http"}
    assert not (imported & forbidden), f"fixture client imports {imported & forbidden}"


def test_a_stale_digest_inside_a_fixture_is_rejected(tmp_path: Path) -> None:
    """Guards against a renamed file masquerading as a current recording."""
    request = a_request()
    path = tmp_path / fixture_filename(request.node_name, prompt_digest(request))
    path.write_text(json.dumps({"prompt_digest": "0" * 64, "output": {"value": "x"}}))

    with pytest.raises(StructuredOutputError, match="regenerate the fixture"):
        FixtureLLMClient(tmp_path).complete_structured(request)


def test_a_fixture_that_violates_the_schema_is_rejected(tmp_path: Path) -> None:
    request = a_request()
    write_fixture(tmp_path, request, {"value": "ok", "unexpected": 1})

    with pytest.raises(StructuredOutputError, match="does not satisfy Answer"):
        FixtureLLMClient(tmp_path).complete_structured(request)


def test_a_fixture_missing_its_output_is_rejected(tmp_path: Path) -> None:
    request = a_request()
    digest = prompt_digest(request)
    path = tmp_path / fixture_filename(request.node_name, digest)
    path.write_text(json.dumps({"prompt_digest": digest}))

    with pytest.raises(StructuredOutputError):
        FixtureLLMClient(tmp_path).complete_structured(request)


# ---------------------------------------------------------------------------
# Client selection
# ---------------------------------------------------------------------------
def test_fixture_mode_builds_the_fixture_client() -> None:
    settings = Settings(_env_file=None, database_url=VALID_URL, demo_mode="fixture")
    assert isinstance(build_llm_client(settings), FixtureLLMClient)


def test_fixture_mode_does_not_import_the_anthropic_sdk() -> None:
    """Not merely unused -- unloaded."""
    sys.modules.pop("anthropic", None)
    settings = Settings(_env_file=None, database_url=VALID_URL, demo_mode="fixture")

    build_llm_client(settings)

    assert "anthropic" not in sys.modules


@pytest.mark.parametrize("mode", ["live", "record"])
def test_a_billable_mode_without_a_key_is_refused(mode: str) -> None:
    """Enforced at construction as well as at startup: a guard that runs in only one
    path is a guard with a gap."""
    settings = Settings.model_construct(
        database_url=VALID_URL, demo_mode=mode, anthropic_api_key=None
    )

    with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
        build_llm_client(settings)
