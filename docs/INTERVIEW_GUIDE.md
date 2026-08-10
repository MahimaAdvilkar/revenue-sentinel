# Interview guide

Answers that match the code. Every one names the file, ADR, or test behind it, and states
its limitation next to its claim — because the limitation is usually the more interesting
half, and being caught overstating is worse than having a gap.

---

## 30 seconds

> Revenue Sentinel watches a synthetic B2B pipeline, notices when a deal has gone quiet
> while the buyer's usage is climbing, investigates it with an agent, and proposes ranked
> interventions — with a policy layer deciding what runs automatically, what needs a human,
> and what is refused outright. It runs offline for $0 and has never made a live model call.
> The interesting part isn't the agent; it's the boundaries around it.

## 2 minutes

> A signal detector — ordinary tested code, not a model — finds a stalled opportunity and
> opens an incident. A LangGraph workflow then plans an investigation, gathers evidence
> through narrow MCP tools, and produces hypotheses that cite specific evidence rows.
>
> The money is computed in Python: $180,000 pipeline, $108,000 weighted, $32,130 at risk.
> The model never does arithmetic the business depends on.
>
> A strategist drafts interventions, a deterministic scorer ranks them, and a policy engine
> classifies each into one of four risk tiers. In the golden scenario that produces one
> allow, one requires-approval, and one denial. The approved one becomes an unsent email
> draft after a human approves via CLI — there's no send capability in the system at all.
>
> Everything is recorded: every tool call, model call, cost entry, and state transition, with
> trace and span IDs. It evaluates itself deterministically, and 1,056 tests run in CI.

## 5 minutes — architecture walkthrough

1. **Ingestion** (`events/`) — a simulated source feed replays a seeded GTM mirror. Replay-safe.
2. **Detection** (`detectors/`) — eight registered, one implemented; a test asserts the count so "eight detectors" can't be claimed by accident.
3. **Orchestration** (`orchestration/`) — LangGraph runs six nodes. Node bodies are thin: an AST test asserts no `db` import and ≤6 statements each (ADR-0002).
4. **Tools** (`mcp/`) — 15 narrow tools, strict schemas, both transports delegating to one dispatcher.
5. **Analytics** (`analytics/`) — the money. Cannot import `intelligence/` or `agents/`; enforced by import-linter contract R3.
6. **Governance** (`governance/`) — a pure policy function over a versioned rule set.
7. **Execution** (`execution/`) — claim the idempotency key, then perform the effect. Never the other way round.
8. **Cost** (`cost/`) — pre-spend admission control, versioned pricing, `Decimal` throughout.
9. **Evaluation** (`evaluation/`) — deterministic checks over persisted rows, each with a negative test.

---

## Why LangGraph?

Because the workflow is a graph with conditional edges and a resume point, and hand-rolling
that is a runtime nobody asked me to own. **But it orchestrates only** (ADR-0002): no domain
logic in node bodies, no framework types in the domain layer, and durable state in Postgres
rather than in a checkpointer.

*Limitation:* I'm not using its durable interrupt/resume. Resume reads business state
(ADR-0016), which means it survives the process dying — proven by destroying the session and
engine and resuming against a fresh one — but it isn't a framework feature I can point at.

## Why not just n8n?

For the happy path, n8n would be fine and faster to build. What it wouldn't give me is the
part this project is actually about: a typed policy tier with default-deny (`governance/tiers.py`),
an idempotency key computed from business values with the row claimed before the effect,
and an evaluator with negative tests proving it can fail. Those are code-level guarantees,
not workflow steps.

*Limitation:* n8n would have shipped in a weekend and has a UI. If the goal were "connect
these five SaaS tools", it's the better answer.

## Why MCP?

It's the tool boundary as a protocol, so the same handlers serve an in-process client and a
real stdio server — verified against an actual subprocess with a real handshake
(`tests/integration/test_transport_parity.py`). Narrow tools by design: `get_open_deals`,
never `run_sql` (rule 15). Every result is stamped with the adapter's own
`INTEGRATION_STATUS`.

*Limitation:* nothing external consumes the stdio server. It's spec-compliant and tested,
not deployed.

## Why not let the LLM calculate revenue?

Because a number that changes between runs can't be audited, and this system's headline
claim is a dollar figure. Stall risk and usage offset are banded lookup tables in
`analytics/pipeline_impact.py` with unit tests; `analytics/` is structurally forbidden from
importing the model layer. The LLM classifies, extracts, summarises, and explains (ADR-0003).

*Limitation:* the bands are heuristics, not calibrated against outcomes — no such dataset
exists for a synthetic account. They're deterministic, versioned, and inspectable, which is
a different claim from accurate.

## How do you prevent prompt injection?

Structurally, not by asking the model nicely (`docs/security-model.md`). Ingested content is
escaped and confined to delimited `<evidence>` blocks, never concatenated into a system
prompt. Six adversarial payloads run in the evaluation suite, and containment is defined as:
untrusted labelling held, delimiters escaped, no unauthorised action record, no
out-of-route tool call, and — the strongest one — the dangerous capability doesn't exist.

*Limitation:* "contained" does **not** mean the model obeyed. It means the payload couldn't
escape its block or authorise anything. Six cases is a corpus, not a security audit.

## How do approvals work?

Tier 2 actions create an `approval_requests` row with an expiry. A human decides via
`uv run rs approve APR-001 --as usr:name`; the decision is an audit event, and expiry is
evaluated on read rather than by a sweeper. Then `rs resume` acts on it.

*Limitation:* `--as` is a **claimed** identity, not an authenticated one (ADR-0018). There is
no authentication anywhere. Self-approval prevention stops an accident, not an impersonation.
That's also why the dashboard has no approve button (ADR-0022) — a button would imply
accountability that doesn't exist.

## What happens if a write times out?

The row is claimed as `EXECUTING` *before* the effect. If the process dies between claiming
and recording, the next attempt finds it still `EXECUTING` and marks it `INDETERMINATE` —
the effect may or may not have happened, and neither guess is safe (ADR-0017).

A human resolves it: `rs actions --status indeterminate`, then `rs reconcile <id> --outcome
occurred|did-not-occur --as <who> --evidence "<what you saw>"`. Evidence is mandatory, only
those two outcomes exist, and reconciling twice is refused (ADR-0025).

*Limitation:* this is **at-least-once, not exactly-once**, and I don't claim otherwise
anywhere. There's deliberately no retry button — a retry becomes reachable only after
someone attests the effect did not occur.

## How do you prevent duplicate side effects?

The idempotency key is a digest of business values — incident, action type, target, payload
digest — and deliberately excludes `run_id`, timestamps, and attempt count
(`execution/idempotency.py`). Keyed by run, a second run would compute a different key and
happily send a second email. `action_records.idempotency_key` is `UNIQUE`, and the row is
claimed before the effect, so the constraint is the lock. `make demo` twice produces zero
duplicates, asserted.

## How do you control cost?

Pre-spend admission: the worst-case cost is computed and checked against every applicable
budget *before* the client is reached, proven by a counting fake that records zero calls
(ADR-0019). Pricing is versioned data, not constants (ADR-0020); everything is `Decimal` at
`NUMERIC(12,6)` — found because a test set a limit one microdollar below a reservation and
watched the call get admitted against a two-decimal column.

*Limitation:* `GLOBAL` admission isn't atomic across concurrent runs. Consumption is
race-free; admission can read a stale figure, so spend can exceed a hard limit by at most
`(concurrent_runs − 1) × worst-case reservation` — zero for one run. Bounded, tested
(`tests/unit/test_budget_overshoot_bound.py`), and deliberately not fixed in v1: the row-lock
fix holds a lock across a model call, and a reservation ledger recreates the
`INDETERMINATE` problem elsewhere (ADR-0026).

## How would this scale from 3 plays to 30–40?

The detector registry and the policy rule set are both data-shaped, so plays are additions
rather than rewrites. What breaks first is the golden-scenario evaluation: one fixture can't
validate forty plays, and I'd need per-play rubrics and real outcome data. Second is the
serialized model calls inside a run — fine at this volume, not at forty.

## What changes with real CRM/email integrations?

Each adapter documents this itself, and the integration catalogue reads those docstrings
rather than restating them. Concretely: OAuth with per-tenant refresh tokens instead of no
auth; cursor pagination; `429` handling that the `RATE_LIMITED` code already anticipates;
`Decimal` parsing at the boundary because HubSpot sends amounts as strings and Salesforce as
floats. And the one that matters — **Gmail draft creation is not idempotent**, which is
precisely why the guarantee has to come from our `UNIQUE` key rather than the provider.

## How would you deploy this?

Today: one API process, one Postgres, one Next.js app, no broker or cache (ADR-0006). To
deploy for real I'd need authentication first, then a migration strategy, then secrets
management, then the concurrency fix above. Trace and span IDs are already recorded and
OTel-shaped; an exporter is a config change, not a redesign.

*Limitation:* nothing is deployed anywhere, and no cloud resource has been created
(rule 20).

## What are the current limitations?

Authentication, browser approval mutation, production identity, live integrations, live
model usage, cloud deployment, OTLP/Prometheus export, real-world precision/recall, and
concurrency-safe global budgets. All nine are listed in `PROJECT_STATUS.md` and
`CAPABILITY_MATRIX.md` rather than discovered by a reader.

The one I'd raise before being asked: **the fixtures are hand-authored** (ADR-0013). They
prove the pipeline, the schemas, and the control behaviour. They prove nothing about whether
the prompts work against a live model.

## What would you build next?

In order: authentication — it unblocks the dashboard, the approval flow, and reconciliation
in the browser, and everything else is gated behind it. Then one real integration end to
end, because the second one is cheap and the first one is where all the wrong assumptions
surface. Then calibrating the scoring bands against real outcomes, which is the only thing
that would let me make a claim about effectiveness rather than about determinism.
