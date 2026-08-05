# ADR-0013: Hand-authored LLM fixtures as the Session 3 bootstrap

**Status:** Accepted
**Date:** 2026-08-04
**Deciders:** Mahima Advilkar

**Qualifies:** [ADR-0007](0007-offline-fixture-demo-mode.md) — which remains accepted.

## Context

[ADR-0007](0007-offline-fixture-demo-mode.md) makes `DEMO_MODE=fixture` the default and
records fixtures from real model calls. It also considered, and **rejected**, exactly
what this ADR now adopts:

> **Skip LLM calls entirely in tests with stub responses.** Rejected: hand-written stubs
> drift from what the model actually returns, and the schema-validation path — which is a
> real source of bugs — stops being tested against realistic output.

That objection is correct. Nothing below makes it go away.

Session 3 nonetheless had a constraint ADR-0007 did not anticipate: **it must spend
nothing.** Recording fixtures requires `DEMO_MODE=record`, an API key, and three to four
Opus calls. That is a small amount of money and a decision that belongs to the person
paying it, not to the session that happens to need fixtures first.

There is also a sequencing problem. Recording a fixture requires a prompt; a prompt is
only final once the schema, the evidence rendering, and the digest inputs are settled —
all of which happen *during* Session 3. Fixtures recorded early in the session would have
been stale by the end of it. The digest includes the schema precisely so that staleness is
loud, and it was: the prompt digest changed several times while the session was in
progress.

## Decision

**Session 3 ships hand-authored fixtures, and builds the recording path without running
it.**

Concretely:

- `fixtures/llm/*.json` are written by hand. Each carries a `$note` field naming itself as
  hand-authored and pointing here.
- `AnthropicLLMClient` and `make record` are written, type-checked, and unit-tested against
  a stubbed SDK. **Neither has been executed against the API.** No live call has been made
  by this project at any point.
- A replayed response reports `is_replay = true`, `stop_reason = "fixture_replay"`, and
  **zero tokens — because zero were consumed**. Migration `0003` adds
  `model_calls.is_replay` so this is a property of the row rather than a convention. No
  token count is estimated, and none is copied from a past call.

**The claim these fixtures support is narrow, and it is the claim that gets made:** they
prove the pipeline, the schemas, the citation gate, and the persistence. They do **not**
prove that the prompts work against a live model.

Four things keep this from becoming permanent:

1. **The fixtures are deliberately un-clean.** The plan is verbose and hedges; the
   hypotheses carry uneven confidences and an explicit "this is weaker than the first"
   caveat. A fixture that reads too tidily would test an unrealistically easy parse.
2. **`make record` ships in the same session**, so regenerating against a real model is one
   command and one decision, not a refactor.
3. **A digest mismatch is loud.** The fixture key covers the model, the effort, both halves
   of the prompt, and the schema. A prompt change produces a `FixtureMissError`, never a
   silent stale replay.
4. **ADR-0007's outstanding debts stay outstanding** — the fixture-freshness check and the
   manual live smoke test remain owed, scheduled for Session 10.

## Alternatives considered

**Record fixtures now.** Rejected for Session 3 only, on the operator's instruction that
the session spend nothing — and independently sensible given that the prompts were still
moving. This is the option to take when regenerating.

**Run in live mode and skip fixtures.** Rejected outright: it defeats ADR-0007 entirely,
makes CI billable and networked, and gives the evaluation suite a nondeterministic subject.

**Ship no fixtures and mark Session 3 blocked on a budget decision.** Rejected: the graph,
the schemas, the citation gate, and the persistence are all testable without a real model
response, and holding a session hostage to a $0.50 decision would trade real progress for
a purity that the recording path preserves anyway.

**Generate fixtures from a cheaper model.** Rejected: a Haiku response to an Opus prompt is
not a more realistic stub than a carefully written one — it is a differently unrealistic
one, with a cost attached and a misleading provenance.

## Consequences

**Easier:** Session 3 costs nothing; CI stays offline and free; the demo runs on a
borrowed laptop with no key; the pipeline is exercised end to end today.

**Harder:** the fixtures encode what their author expected a model to return. Realistic
failure modes — a model that hedges into an unparseable shape, that omits a required
field, that cites plausibly but wrongly — are represented only as far as they were
imagined. The live path remains **unexercised**, which is a real gap and is stated as one
in `PROJECT_STATUS.md` and the README rather than left for a reader to infer.

**We now owe:** the honest sentence, wherever this comes up — *"the offline fixtures are
hand-authored and the recording path has not been run, so they prove the pipeline and the
schemas, not that the prompts work against a live model."* And, before any demo where the
live path is claimed to work, an actual `make record` and an actual smoke test.

## Revisit when

Any of three, whichever comes first:

1. **The operator approves spending.** Then run `make record`, replace the hand-authored
   files, and supersede this ADR — the fixtures become recorded and ADR-0007 applies
   unqualified.
2. **A prompt or schema change makes the hand-authored responses implausible** — for
   example a schema that requires reasoning the author cannot convincingly fake. At that
   point a hand-authored fixture is no longer a bootstrap but a fiction.
3. **Session 10**, when the fixture-freshness check and live smoke test are due. Those
   were designed assuming recorded fixtures, and a freshness check over hand-authored
   files checks only that someone remembered to edit them.
