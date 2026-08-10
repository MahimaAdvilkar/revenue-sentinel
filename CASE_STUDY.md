# Revenue Sentinel — case study

An agentic GTM control tower that investigates stalled pipeline, proposes ranked
interventions, and refuses to do anything consequential without a person. It runs offline,
reproducibly, for **$0.000000**, and has never made a live model call.

This is a walkthrough of one scenario end to end, with the design decision introduced at the
point the scenario reaches it — because that is the order in which the decisions actually
mattered.

---

## The problem

A B2B sales team has more pipeline than attention. A $180,000 opportunity sits in Proposal;
the rep last made contact fourteen days ago; meanwhile the buyer's product usage is *rising* —
feature events from 1,250 to 1,750 week over week, active users from 12 to 19.

That contradiction is the whole point. Silence usually means a deal is dying; rising usage
usually means it is alive. Resolving it takes someone reading a CRM record, an email thread,
a usage chart, and a support queue — perhaps twenty minutes per deal, which is why nobody
does it for every deal every week.

The failure mode of automating this badly is not "the agent is unhelpful". It is an agent
that emails a customer something wrong, or reports a revenue figure nobody can reproduce.

## Design goals

1. **Deterministic where it matters.** Money, policy, and ranking are ordinary tested code.
2. **Nothing consequential without a person.** Outbound messages and material CRM changes require explicit approval.
3. **Honest by construction.** Anything simulated says so, in code and on screen.
4. **Reproducible at zero cost.** The demo runs offline with no API key.

Everything below follows from those four.

---

## Signal → incident

A detector — ordinary code with unit tests, not a model — scores 15 opportunities and finds
one signal. `INC-001` opens at HIGH severity, where severity is a banded function of weighted
pipeline value, so identical inputs always produce an identical band.

Eight detectors are registered and exactly one is implemented; the other seven raise
`NotImplementedError`. A test asserts the count, so "eight detectors" cannot be claimed
anywhere, including by accident.

## Investigation → evidence

A LangGraph workflow plans the investigation and gathers evidence: six items across four
source systems.

**LangGraph orchestrates; it is not the architecture** (ADR-0002). Node bodies are thin —
an AST test asserts no node imports `db` and none exceeds six statements. Framework types
never reach the domain layer. The reason is scar tissue in general form: frameworks absorb
business logic gradually, and by the time it hurts, the logic is unreachable without the
framework.

**Evidence arrives through narrow MCP tools** — `crm_get_opportunity`, never `run_sql`
(rule 15). Fifteen tools, each with a strict Pydantic schema (`extra="forbid"` → the wire
rejects unknown arguments), a documented blast radius, and a tier. Two transports — an
in-process client and a real stdio server — delegate to one dispatcher, so they cannot drift;
a test drives the stdio server as an actual subprocess through a real MCP handshake and
asserts payload equality with the in-process path.

Every result carries `integration_status` read from the adapter that served it. The badge on
the dashboard is therefore derived from the code that answered the request, not from a
constant somewhere convenient.

**All ingested content is untrusted** (rule 14). Evidence is escaped and confined to
delimited blocks, never concatenated into a system prompt. Six adversarial payloads run in
the evaluation suite; containment is defined structurally — labelling held, delimiters
escaped, no unauthorised action, no out-of-route tool call, and the dangerous capability
absent — because "the model ignored it" is not a security property.

## Hypotheses → citations

Two hypotheses, each citing specific evidence. The citations are **foreign keys**: a
hypothesis citing invented evidence fails to persist at all, and the run aborts leaving the
tables empty. That is a schema refusing an alternative, not a prompt asking for good
behaviour.

## Impact — the arithmetic the model never touches

Pipeline **$180,000** → weighted **$108,000** → at risk **$32,130**.

Stall risk (0.35) and usage offset (0.15) are banded lookup tables in `analytics/`, unit
tested and versioned (ADR-0008). `analytics/` is structurally forbidden from importing
`intelligence/` or `agents/` — an import-linter contract, asserted again per-module by an
AST test.

This is the single most load-bearing decision in the project (ADR-0003). A headline dollar
figure produced by a model is a figure that changes between runs and cannot be audited. The
LLM classifies, extracts, summarises, and explains; it never performs arithmetic the business
depends on.

*The honest caveat:* the bands are heuristics, not calibrated against outcomes — no such
dataset exists for a synthetic account. They are deterministic, versioned, and inspectable,
which is a different claim from accurate.

## Strategy → policy → three different answers

A strategist drafts interventions and supplies **no numbers and no ordering**; a
deterministic scorer ranks them and keeps three. Each hits the policy layer and gets a
different answer: a CRM task is **allowed** and runs automatically; an email to the champion
**requires approval**; a discount is **denied**.

**Policy is a pure function over a versioned rule set** (ADR-0015) — no I/O, no clock; 25
identical evaluations asserted identical. Default-deny is a runtime property rather than a
dead branch: an unmapped action falls through a lookup with a denying default, so the safe
answer needs no code path to be remembered. Ambiguity escalates by `max()` to the higher tier.

## Approval → execution → the capability that does not exist

Approval is a recorded event with an actor and an expiry, decided through the CLI. The
approved action becomes an **unsent email draft**.

There is no `send_email` tool and no send method on `MessagingPort`. Tier 3 is not blocked at
runtime — it is absent from the interface. A `send_email` that the policy layer always denied
would still be a system that can send email; this is a system that cannot.

`--as` is a **claimed** identity, not an authenticated one (ADR-0018). Which is exactly why
the dashboard renders the CLI command and offers no approve button (ADR-0022): with no
authenticated identity, a button implies an accountable user who does not exist. Three tests
enforce it — no mutation route in the API, none in the generated TypeScript contract, and no
`<button>`, `<form>`, or `<input>` on the screen.

## Idempotency, and the honest unknown

The idempotency key is a digest of business values — incident, action type, target, payload —
and deliberately **excludes** `run_id`, timestamps, and attempt count. Keyed by run, a second
run computes a different key and cheerfully sends a second email. The row is claimed
**before** the effect, so the `UNIQUE` constraint is the lock rather than an advisory note.
`make demo` twice produces zero duplicate effects, asserted.

When a process dies between claiming and recording, the outcome is genuinely unknown.
The system records `INDETERMINATE` rather than guessing (ADR-0017), and a human resolves it
with mandatory evidence, two possible outcomes, and no retry button — a retry becomes
reachable only after someone attests the effect did not occur (ADR-0025). **This is
at-least-once, not exactly-once**, and nothing in the system claims otherwise.

## Cost governance

Admission control runs *before* the client: the worst case is computed and checked against
every applicable budget, proven by a counting fake that records zero calls (ADR-0019).
Pricing is versioned data (ADR-0020) and everything is `Decimal` at `NUMERIC(12,6)` — a
precision defect found by a test that set a limit one microdollar below a reservation and
watched the call be admitted against a two-decimal column.

Total spend: **$0.000000**, printed unrounded, because fixture mode consumes zero tokens.
The dashboard reports cache effectiveness as *never observed* rather than `0%` — the counters
are zero because no live call has ever been made, and a zero would be a measurement claim the
system cannot support.

`GLOBAL` admission is not atomic across concurrent runs. Consumption is race-free; admission
can read a stale figure, so spend may exceed a hard limit by at most
`(concurrent_runs − 1) × worst-case reservation` — exactly zero for one run. That bound is
computed by code and unit tested, and left unfixed deliberately: a row lock held across a
model call is worse than the race, and a reservation ledger recreates the
claimed-but-unresolved problem elsewhere (ADR-0026).

## Why fixture replay exists

`FixtureLLMClient` holds no API key, no HTTP client, and no import of `anthropic`. There is
no fallback branch — not a disabled one; it does not exist (ADR-0007). A full run completes
with `socket.socket` refusing to open.

That buys reproducibility, zero cost, and a demo that cannot fail because of a network, a
rate limit, or model variance.

**What it does not buy, stated plainly:** the fixtures are *hand-authored*, not recorded
(ADR-0013). They prove the pipeline, the schemas, the citation gate, and the control
behaviour. **They prove nothing about real model quality**, and every replayed row says so —
`is_replay = true`, zero tokens, `stop_reason = fixture_replay`. A fixture-freshness gate
fails CI in seconds if a prompt or renderer changes without the fixtures being regenerated,
and it documents precisely what it cannot detect (ADR-0024).

## Evaluation and security testing

`make eval` runs deterministic structural checks over persisted rows — no LLM judge (ADR-0021),
because a hand-authored fixture judging a hand-authored fixture is circular. Every check has a
**negative test** proving it can fail; a rubric nobody has seen fail is one nobody knows works.
Evaluation history is append-only and ordered by an identity column, so a later pass cannot
erase the record of an earlier failure — and the screen shows the list, never a status.

## Scaling from one golden scenario

The detector registry and the policy rule set are data-shaped, so plays are additions. What
breaks first is evaluation: one fixture cannot validate forty plays, and per-play rubrics need
real outcome data that does not exist here. Second is serialized model calls within a run.
Third is the concurrency boundary above, whose revisit trigger is written down: the first
deployment that runs independent investigations concurrently.

## What I would change with real integrations and real traffic

**Authentication first** — it gates the dashboard, the approval flow, and reconciliation in
the browser, and everything else is downstream of it.

**One integration end to end before the second**, because the first is where the wrong
assumptions surface: OAuth with per-tenant refresh tokens, cursor pagination, `429` handling,
`Decimal` parsing at the boundary. And the one that changes the design: **Gmail draft creation
is not idempotent**, which is exactly why the guarantee must come from our own `UNIQUE` key
rather than the provider's.

**Calibrate the bands against outcomes**, which is the only thing that would let me claim
effectiveness rather than determinism. Until then the honest statement is that this system is
reproducible and auditable, and unproven against reality.

**Recorded fixtures instead of hand-authored ones**, at which point the prompts get tested
rather than assumed.

---

## Numbers

| | |
|---|---|
| Backend tests | 1,056 (0 skipped, 0 xfailed; 1 live test deselected by default) |
| Frontend tests | 60 |
| CI jobs | 6, all green |
| ADRs | 26 |
| MCP tools | 15 narrow, 0 general-purpose |
| Total spend | **$0.000000** |
| Live model calls | **0** |

## Still not implemented

Authentication · browser approval mutation · production identity · live integrations · live
model usage · cloud deployment · OTLP/Prometheus export · real-world precision/recall ·
concurrency-safe `GLOBAL` budget enforcement.

All nine are recorded in `PROJECT_STATUS.md` and `CAPABILITY_MATRIX.md` rather than left for
a reader to discover.
