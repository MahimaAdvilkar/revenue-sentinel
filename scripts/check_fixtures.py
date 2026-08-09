"""Fail when a recorded LLM fixture no longer matches the code that produced it.

A fixture's filename carries the digest of the prompt it was recorded against, and
`FixtureLLMClient` refuses a mismatch rather than replaying a stale answer. That is the
right behaviour, but it surfaces late: the first person to run `make demo` after someone
edits a system prompt gets a `StructuredOutputError`, and has to work out why.

This finds it in CI instead, **without a database, without a network, and without making
a model call** -- so it can run in seconds on every push.

## What it checks

1. **Internal consistency.** Every fixture's recorded `prompt_digest` matches the digest
   in its own filename.
2. **Schema currency.** Every fixture still validates against the schema its node
   declares, so an additive schema change that would silently deserialize is caught.
3. **Template drift.** Every fixture records a `template_digest` over the code that
   composes its prompt: the node's system prompt, its output schema, the agent function
   that builds the request, and every renderer in `prompts.py`. Editing any of those
   changes the digest, and this fails.
4. **Coverage.** Every LLM call site has a fixture, so a newly added node cannot ship
   with nothing recorded for it.

## What it deliberately cannot prove

**It cannot recompute the real prompt digest.** That digest covers the *rendered* user
content, which depends on seeded data -- a database this check does not have and does not
want. So a change that alters rendered content without touching any template (new seed
data, a different incident) is invisible here. The integration suite catches that,
because it runs the graph against a real database and the client verifies the true digest
on load. Between the two, a stale fixture cannot reach `main` unnoticed.

**A passing template digest does not mean the recorded output is correct.** It means the
prompt-composing code has not changed since the fixture was last verified. The fixtures
are hand-authored (ADR-0013); their content was never a model's output and this check
makes no claim about their quality.

**It is conservative in one direction.** A docstring edit inside a renderer changes the
template digest even though rendered output is identical. That is a deliberate choice:
a false alarm costs a re-verification, and a missed change costs a demo that fails in
front of someone.

## Re-stamping

`--stamp` rewrites `template_digest` in every fixture. It is only honest to run it
**immediately after `make demo` passes**, because the demo recomputes the true prompt
digest against real data -- which is the evidence that the fixtures still match the
current templates. Stamping without that is recording an assumption as a fact.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType
from typing import Final

from pydantic import BaseModel, ValidationError

from revenue_sentinel.agents import analyst, planner, researcher, strategist
from revenue_sentinel.intelligence import prompts
from revenue_sentinel.intelligence.digest import schema_fingerprint
from revenue_sentinel.intelligence.fixture_client import DIGEST_FILENAME_LENGTH
from revenue_sentinel.intelligence.schemas import (
    EvidenceSelection,
    HypothesisSet,
    InterventionSet,
    InvestigationPlan,
)

FIXTURE_DIR: Final = Path("fixtures/llm")

TEMPLATE_DIGEST_KEY: Final = "template_digest"


@dataclass(frozen=True, slots=True)
class CallSite:
    """One LLM call site and everything static that shapes its prompt."""

    node_name: str
    system_prompt: str
    schema: type[BaseModel]
    builder: FunctionType


CALL_SITES: Final[tuple[CallSite, ...]] = (
    CallSite(
        node_name="plan_investigation",
        system_prompt=prompts.PLANNER_SYSTEM_PROMPT,
        schema=InvestigationPlan,
        builder=planner.plan_investigation,
    ),
    CallSite(
        node_name="collect_evidence",
        system_prompt=prompts.RESEARCHER_SYSTEM_PROMPT,
        schema=EvidenceSelection,
        builder=researcher.select_sources,
    ),
    CallSite(
        node_name="generate_hypotheses",
        system_prompt=prompts.ANALYST_SYSTEM_PROMPT,
        schema=HypothesisSet,
        builder=analyst.generate_hypotheses,
    ),
    CallSite(
        node_name="draft_interventions",
        system_prompt=prompts.STRATEGIST_SYSTEM_PROMPT,
        schema=InterventionSet,
        builder=strategist.draft_interventions,
    ),
)
"""Every call site. A node added without an entry fails the coverage check below rather
than silently going unverified."""

SCHEMA_BY_NODE: Final[dict[str, type[BaseModel]]] = {
    site.node_name: site.schema for site in CALL_SITES
}


def _renderer_sources() -> str:
    """The source of every rendering helper in `prompts.py`, in a fixed order.

    The renderers are what turn seeded rows into user content, so an edit to any of them
    changes what a live call would send -- and therefore invalidates a fixture recorded
    before the edit. Hashing the source is the only way to see that without data.
    """
    functions = sorted(
        (name, value)
        for name, value in vars(prompts).items()
        if isinstance(value, FunctionType) and value.__module__ == prompts.__name__
    )
    return "\n".join(f"{name}\n{inspect.getsource(value)}" for name, value in functions)


def template_digest(site: CallSite) -> str:
    """A digest over everything static that shapes this node's prompt.

    Deliberately *not* the same value as `prompt_digest`: that one covers the rendered
    user content and cannot be computed without a database. This covers the code that
    would render it.
    """
    parts = (
        site.node_name,
        site.system_prompt,
        schema_fingerprint(site.schema),
        inspect.getsource(site.builder),
        _renderer_sources(),
    )
    hasher = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        hasher.update(str(len(encoded)).encode("ascii"))
        hasher.update(b"\x00")
        hasher.update(encoded)
    return hasher.hexdigest()


def _problems(fixtures: list[Path]) -> list[str]:
    problems: list[str] = []
    seen_nodes: set[str] = set()
    expected_templates = {site.node_name: template_digest(site) for site in CALL_SITES}

    for path in fixtures:
        payload = json.loads(path.read_text(encoding="utf-8"))
        node = payload.get("node_name")
        recorded = payload.get("prompt_digest")

        if not isinstance(node, str) or not isinstance(recorded, str):
            problems.append(f"{path.name}: missing node_name or prompt_digest")
            continue

        seen_nodes.add(node)

        # The filename is `<node>.<digest[:12]>.json`. A mismatch means the file was
        # renamed or the digest edited -- either way the client would refuse it.
        expected_name = f"{node}.{recorded[:DIGEST_FILENAME_LENGTH]}.json"
        if path.name != expected_name:
            problems.append(
                f"{path.name}: filename disagrees with its own recorded digest "
                f"(expected {expected_name})"
            )

        schema = SCHEMA_BY_NODE.get(node)
        if schema is None:
            problems.append(f"{path.name}: node {node!r} has no known call site")
            continue

        try:
            schema.model_validate(payload.get("output"))
        except ValidationError as error:
            problems.append(
                f"{path.name}: no longer satisfies {schema.__name__} -- the schema "
                f"changed and the fixture was not regenerated ({error.error_count()} errors)"
            )

        stamped = payload.get(TEMPLATE_DIGEST_KEY)
        if not isinstance(stamped, str):
            problems.append(
                f"{path.name}: no {TEMPLATE_DIGEST_KEY}. Verify with 'make demo', then "
                f"run 'python -m scripts.check_fixtures --stamp'."
            )
        elif stamped != expected_templates[node]:
            problems.append(
                f"{path.name}: the prompt templates changed since this fixture was "
                f"verified (system prompt, output schema, {node} builder, or a renderer "
                f"in prompts.py). The recorded response was produced against different "
                f"code."
            )

    missing = sorted(set(SCHEMA_BY_NODE) - seen_nodes)
    problems.extend(
        f"no fixture recorded for call site {node!r} -- the offline demo would raise "
        f"FixtureMissError"
        for node in missing
    )
    return problems


def stamp(fixtures: list[Path]) -> int:
    """Rewrite `template_digest` in every fixture. See the module docstring's warning."""
    digests = {site.node_name: template_digest(site) for site in CALL_SITES}
    for path in fixtures:
        payload = json.loads(path.read_text(encoding="utf-8"))
        node = payload.get("node_name")
        if node not in digests:
            print(f"  - skipped {path.name}: unknown node {node!r}")
            continue
        payload[TEMPLATE_DIGEST_KEY] = digests[node]
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  - stamped {path.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stamp",
        action="store_true",
        help="rewrite template_digest -- only valid immediately after 'make demo' passes",
    )
    args = parser.parse_args(argv)

    fixtures = sorted(FIXTURE_DIR.glob("*.json"))
    if not fixtures:
        print(f"no fixtures found in {FIXTURE_DIR} -- the offline demo cannot run")
        return 1

    if args.stamp:
        print("Stamping template digests. This is only honest right after 'make demo':")
        return stamp(fixtures)

    problems = _problems(fixtures)
    if problems:
        print("Fixture freshness check FAILED:\n")
        for problem in problems:
            print(f"  - {problem}")
        print(
            "\nIf a prompt or schema changed deliberately, regenerate the fixtures. "
            "Recording requires an API key and costs money -- see ADR-0013."
        )
        return 1

    print(
        f"Fixture freshness OK: {len(CALL_SITES)} call sites, {len(fixtures)} fixtures, "
        f"digests and templates current."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
