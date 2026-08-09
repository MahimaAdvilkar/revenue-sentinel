"""The fixture freshness check.

The check exists so a stale fixture fails in seconds on every push rather than as a
`StructuredOutputError` in front of whoever runs the demo next. These tests drive it
against deliberately broken fixture directories, because a checker that has never failed
is a checker nobody knows works.

They also pin what it *cannot* prove -- see the last test. Overstating the guarantee
would be worse than not having the check.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import check_fixtures


@pytest.fixture
def fixture_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of the real fixtures, isolated so tests can corrupt them."""
    target = tmp_path / "llm"
    target.mkdir()
    for source in sorted(Path("fixtures/llm").glob("*.json")):
        (target / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(check_fixtures, "FIXTURE_DIR", target)
    return target


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_the_committed_fixtures_pass(fixture_dir: Path) -> None:
    assert check_fixtures.main([]) == 0


def test_every_call_site_has_a_fixture() -> None:
    """Coverage, against the real directory rather than a copy."""
    recorded = {
        json.loads(path.read_text(encoding="utf-8"))["node_name"]
        for path in Path("fixtures/llm").glob("*.json")
    }
    assert {site.node_name for site in check_fixtures.CALL_SITES} <= recorded


def test_a_deleted_fixture_fails_the_coverage_check(fixture_dir: Path) -> None:
    """A newly added node with nothing recorded would raise FixtureMissError at runtime."""
    next(fixture_dir.glob("plan_investigation.*.json")).unlink()

    problems = check_fixtures._problems(sorted(fixture_dir.glob("*.json")))

    assert any("plan_investigation" in problem and "no fixture" in problem for problem in problems)


def test_an_empty_directory_fails_rather_than_passing_vacuously(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_fixtures, "FIXTURE_DIR", tmp_path)
    assert check_fixtures.main([]) == 1


def test_a_renamed_fixture_fails(fixture_dir: Path) -> None:
    """The filename carries the digest. A rename breaks the identity the client uses."""
    path = next(fixture_dir.glob("plan_investigation.*.json"))
    path.rename(fixture_dir / "plan_investigation.deadbeef0000.json")

    problems = check_fixtures._problems(sorted(fixture_dir.glob("*.json")))

    assert any("filename disagrees" in problem for problem in problems)


def test_an_output_that_no_longer_satisfies_its_schema_fails(fixture_dir: Path) -> None:
    """The failure an additive schema change would otherwise hide."""
    path = next(fixture_dir.glob("generate_hypotheses.*.json"))
    payload = _load(path)
    payload["output"] = {"hypotheses": [{"rank": 1}]}
    _write(path, payload)

    problems = check_fixtures._problems(sorted(fixture_dir.glob("*.json")))

    assert any("no longer satisfies HypothesisSet" in problem for problem in problems)


def test_an_edited_system_prompt_invalidates_the_fixture(
    fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline case: someone edits a prompt and the recorded answer is now stale.

    Today that surfaces as a demo failure. This makes it a CI failure.
    """
    site = check_fixtures.CALL_SITES[0]
    monkeypatch.setattr(
        check_fixtures,
        "CALL_SITES",
        (
            check_fixtures.CallSite(
                node_name=site.node_name,
                system_prompt=site.system_prompt + "\nAlso, be more concise.",
                schema=site.schema,
                builder=site.builder,
            ),
        ),
    )
    monkeypatch.setattr(
        check_fixtures, "SCHEMA_BY_NODE", {site.node_name: site.schema}, raising=True
    )

    paths = sorted(fixture_dir.glob(f"{site.node_name}.*.json"))
    problems = check_fixtures._problems(paths)

    assert any("templates changed" in problem for problem in problems)


def test_an_edited_renderer_invalidates_every_fixture(
    fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Renderers turn seeded rows into user content, so editing one changes what a live
    call would send -- for every node that renders anything."""

    def _replacement(*_: object, **__: object) -> str:
        return "different"

    monkeypatch.setattr(check_fixtures.prompts, "render_incident_context", _replacement)

    problems = check_fixtures._problems(sorted(fixture_dir.glob("*.json")))

    changed = [problem for problem in problems if "templates changed" in problem]
    assert len(changed) == len(check_fixtures.CALL_SITES)


def test_a_missing_template_digest_fails_rather_than_being_skipped(fixture_dir: Path) -> None:
    """Absent evidence is not evidence of freshness."""
    path = next(fixture_dir.glob("plan_investigation.*.json"))
    payload = _load(path)
    del payload[check_fixtures.TEMPLATE_DIGEST_KEY]
    _write(path, payload)

    problems = check_fixtures._problems(sorted(fixture_dir.glob("*.json")))

    assert any(check_fixtures.TEMPLATE_DIGEST_KEY in problem for problem in problems)


def test_stamping_rewrites_only_the_digest(fixture_dir: Path) -> None:
    path = next(fixture_dir.glob("plan_investigation.*.json"))
    before = _load(path)
    before[check_fixtures.TEMPLATE_DIGEST_KEY] = "stale"
    _write(path, before)

    assert check_fixtures.main(["--stamp"]) == 0

    after = _load(path)
    assert after[check_fixtures.TEMPLATE_DIGEST_KEY] != "stale"
    assert after["output"] == before["output"]
    assert after["prompt_digest"] == before["prompt_digest"]
    assert check_fixtures.main([]) == 0


def test_the_check_needs_no_database_or_network(fixture_dir: Path) -> None:
    """Stated as a test because it is the reason this runs on every push.

    `_problems` imports no session, opens no socket, and makes no model call -- the whole
    check is source inspection and JSON. If that ever stops being true, this fails by
    hanging or erroring rather than by review.
    """
    import socket

    def _refuse(*_: object, **__: object) -> None:
        raise AssertionError("the fixture check must not open a socket")

    original = socket.socket
    socket.socket = _refuse  # type: ignore[assignment,misc]
    try:
        assert check_fixtures._problems(sorted(fixture_dir.glob("*.json"))) == []
    finally:
        socket.socket = original  # type: ignore[misc]


def test_the_check_cannot_see_rendered_content_changes(fixture_dir: Path) -> None:
    """The documented limitation, pinned.

    The real prompt digest covers rendered user content, which depends on seeded data.
    Changing that data -- a different incident, a re-seed -- would invalidate the fixture
    at runtime and is invisible here. The integration suite is what catches it.

    This test exists so nobody reads a green fixture job as "the fixtures are correct".
    """
    assert (
        check_fixtures.template_digest(check_fixtures.CALL_SITES[0])
        != json.loads(
            next(fixture_dir.glob("plan_investigation.*.json")).read_text(encoding="utf-8")
        )["prompt_digest"]
    ), "the template digest is not, and cannot be, the prompt digest"
