# ADR-0007: Offline fixture demo mode is the default

**Status:** Accepted
**Date:** 2026-08-01
**Deciders:** Mahima Advilkar

## Context

This system will be demonstrated in interviews. The demo path therefore has requirements
that have nothing to do with the architecture and everything to do with the setting: it
must work on unfamiliar wifi, on a borrowed machine, without an API key, without a budget,
and it must produce the same output every time so the narration matches the screen.

A live model call fails all five of those requirements at once. It can be slow, rate
limited, network dependent, billable, and — most damaging — *different this time*. A demo
where the presenter says "it usually says two hypotheses here" has already lost the room.

There is a second, less obvious reason. Requirement 15 is that the system evaluates whether
the workflow behaved correctly. An evaluation suite whose subject is nondeterministic
cannot distinguish a regression from a re-roll.

## Decision

**`DEMO_MODE=fixture` is the default.** The demo, the test suite, and CI all run fully
offline against recorded model responses. Live-model mode is opt-in.

| Mode | Model calls | Requires key | Determinism | Used for |
|---|---|---|---|---|
| `fixture` (**default**) | Replayed from `fixtures/llm/` | No | Total | Demo, tests, CI, evaluation |
| `live` | Real Claude API | Yes | No | Development, live smoke test, recording new fixtures |
| `record` | Real API, writes fixtures | Yes | No | Regenerating fixtures after a prompt change |

Mechanics:

- Fixtures are keyed by a **prompt digest** — a hash over the rendered prompt, model ID,
  and schema. Same prompt in, same response out.
- The LLM client is a port. `FixtureLLMClient` and `AnthropicLLMClient` implement the same
  interface, and no call site knows which is bound.
- **A fixture miss is an error, never a fallback.** In `fixture` mode, a digest with no
  recorded response raises immediately. It does not quietly call the API.
- Determinism extends past the model: fixed seed (`SEED=20260801`) for seed data, and an
  injected evaluation timestamp rather than `now()`.

The fixture-miss rule is the one that matters most. A silent fallback would turn an offline
test into a billable network call the first time a prompt changed — quietly, in CI, and
possibly during a demo.

## Alternatives considered

**Live model calls with a low temperature.** Rejected on two grounds: sampling parameters
are not accepted on the current Claude models at all, and even if they were, "usually the
same" is not determinism. It also leaves the network and budget dependencies untouched.

**Fixture mode as an opt-in flag, live as the default.** Rejected: defaults are what
happens under pressure. If `make demo` needs a key and a network, the demo is fragile
exactly when it matters.

**Snapshot the whole workflow output rather than individual model responses.** Rejected: a
single opaque snapshot tests nothing about the intermediate steps, and any change anywhere
invalidates it wholesale. Per-call fixtures keep the graph genuinely exercised — every
node, every policy decision, every idempotency check runs for real.

**Skip LLM calls entirely in tests with stub responses.** Rejected: hand-written stubs
drift from what the model actually returns, and the schema-validation path — which is a
real source of bugs — stops being tested against realistic output.

## Consequences

**Easier:** the demo always works; CI needs no secret; tests are fast and free; the
evaluation suite has a stable subject; a reviewer can clone and run with zero setup.

**Harder:** fixtures must be regenerated whenever a prompt or schema changes, and a stale
fixture tests yesterday's prompt against today's code. Fixture mode also cannot catch
genuine model behaviour changes — a prompt that has quietly stopped working looks fine
offline.

**We now owe:** a `make record` target, a fixture-freshness check that fails when a prompt
template changes without its fixtures being regenerated, and a **live smoke test** run
manually before any demo. The smoke test's only job is to confirm the live path still
validates against its schemas — it is the counterweight to everything fixture mode cannot
see.

## Revisit when

The live smoke test starts diverging from fixtures often enough that fixtures are
misleading rather than helpful, or the system acquires behaviour that genuinely cannot be
recorded (streaming interaction, multi-turn negotiation with a user). At that point the
answer is a richer recording format, not abandoning determinism.
