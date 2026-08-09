# ADR-0024: Fixture freshness is checked by a deliberately partial digest

**Status:** Accepted
**Date:** 2026-08-08
**Deciders:** Mahima Advilkar

## Context

Every LLM fixture is keyed by `prompt_digest` — a SHA-256 over the model id, the effort
level, the system prompt, the **rendered user content**, and the output schema
(`intelligence/digest.py`). `FixtureLLMClient` recomputes it on load and refuses a
mismatch rather than replaying a stale answer, which is the correct behaviour and is not
in question here.

The problem is *when* that refusal happens. Editing a system prompt or a renderer in
`prompts.py` invalidates every recorded fixture, and nothing says so until somebody runs
the demo or the integration suite and gets a `StructuredOutputError`. That is late, and it
is late in the most expensive place: in front of whoever is being shown the project.

The obvious fix — recompute the real digest in CI — is not available. The digest covers
rendered user content, which is rendered from seeded rows. Recomputing it needs a
database, a seed, and effectively a workflow run. The integration suite already does
exactly that, so a CI job that repeats it adds minutes and no information.

So the question is what can be checked in seconds, with no database and no network, that
catches the realistic failure.

## Decision

**Each fixture records a `template_digest` over the code that composes its prompt, and
`scripts/check_fixtures.py` recomputes and compares it.** The digest covers:

- the node's system prompt constant,
- its output schema fingerprint,
- the source of the agent function that builds the `LLMRequest`,
- the source of every renderer function in `prompts.py`.

It deliberately **does not** cover rendered user content, and it is **not** the same value
as `prompt_digest`. A test asserts they differ, so nobody can come to believe the check
proves more than it does.

**What this catches, in seconds and without infrastructure:** an edited system prompt, a
changed output schema, an edited request builder, an edited renderer, a renamed fixture, a
fixture whose recorded output no longer satisfies its schema, and a call site with no
fixture at all.

**What it cannot catch:** a change to the *data* the renderers read. New seed data, a
different incident, a re-seed — all of these change the rendered content and therefore the
real digest, and all are invisible here. The integration suite owns that half, because it
runs the graph against a real database and the client verifies the true digest on load.
Between the two, a stale fixture cannot reach `main` unnoticed. Neither alone is
sufficient, and the split is the point.

**A passing check says nothing about fixture quality.** The fixtures are hand-authored
(ADR-0013). This proves the prompt-composing code has not moved since they were last
verified; it makes no claim that the recorded responses are good ones.

### The `--stamp` protocol

`--stamp` rewrites `template_digest` in every fixture. It is honest **only immediately
after `make demo` passes**, because the demo recomputes the real digest against real data
— which is the evidence that the fixtures still match the current templates. Stamping at
any other moment records an assumption as a fact, and the module docstring says so in
those words.

## Alternatives considered

**Recompute the real digest in CI.** Rejected: needs a database and a seeded workflow,
which the integration suite already runs. The fast check exists precisely to be fast.

**Hash the whole `prompts.py` module source.** Rejected as too coarse in one direction and
too narrow in another: a docstring edit anywhere in the module would trip all four
fixtures, while an edit to an agent's request builder — which lives in `agents/`, not
`prompts/` — would trip none.

**Hash only the system prompts.** Rejected: it misses renderer changes, which alter user
content just as surely and are the edit most likely to be made without thinking about
fixtures.

**Rely on the integration suite alone.** Rejected. It does catch this, but only after a
database spins up and a workflow runs, and its failure message is about a digest mismatch
rather than about the prompt someone just edited. A fast, specific failure is worth a
second mechanism.

**Store no digest and re-derive freshness from git history** (has `prompts.py` changed
since the fixture file?). Rejected: it breaks under rebase, squash, and any history
rewrite, and it would report a change that provably could not affect rendering.

## Consequences

**Easier.** A prompt edit fails in seconds on every push, with a message naming the node
and the four things that could have changed. The check runs with no database, no network,
and no API key, so it costs nothing and cannot be skipped for environmental reasons.

**Harder.** The digest is conservative: a docstring edit inside a renderer trips it even
though rendered output is identical. That is a deliberate trade — a false alarm costs one
re-verification; a missed change costs a demo that fails in front of someone.

**We now owe** the discipline that `--stamp` follows a passing `make demo` and never
precedes one, and that any new LLM call site is added to `CALL_SITES` in
`scripts/check_fixtures.py`. A node absent from that tuple fails the coverage check rather
than passing silently, so the obligation is enforced rather than remembered.

Twelve tests in `tests/unit/test_check_fixtures.py` drive the checker against deliberately
broken fixture directories — a renamed file, a schema-violating output, an edited system
prompt, an edited renderer, a missing digest, an empty directory. A gate nobody has seen
fail is a gate nobody knows works.

## Revisit when

1. **Fixtures are ever recorded from a live model** (`make record` is run, ADR-0013). The
   cost of a false alarm rises sharply once regenerating means spending money, and the
   digest's conservatism should be narrowed at that point — most likely by hashing
   renderer bodies with docstrings stripped.
2. **The number of call sites grows past a handful**, at which point hashing *every*
   renderer for *every* node stops being proportionate and the digest should be narrowed
   to the renderers a node actually reaches.
3. **A prompt-templating library is introduced.** Templates in files rather than in Python
   source would make the real digest computable from the templates plus a recorded
   rendering context, which would close the gap this ADR documents rather than splitting
   it across two checks.
