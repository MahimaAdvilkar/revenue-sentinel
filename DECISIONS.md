# Decision Log

**Last updated:** 2026-08-01 (Phase 1)

Running log of decisions. Substantial architectural decisions get a full record in
[`docs/architecture-decisions/`](docs/architecture-decisions/); everything else lives here
with a one-line rationale.

---

## Architecture Decision Records

| ADR | Decision | Status |
|---|---|---|
| [0001](docs/architecture-decisions/0001-modular-monolith.md) | Modular monolith with `import-linter`-enforced boundaries | Accepted |
| [0002](docs/architecture-decisions/0002-langgraph-orchestration-boundary.md) | LangGraph orchestrates; it is not the architecture | Accepted |
| [0003](docs/architecture-decisions/0003-deterministic-vs-llm-boundary.md) | Deterministic code owns money, policy, and ranking | Accepted |
| [0004](docs/architecture-decisions/0004-simulated-integrations.md) | Simulated integrations behind real ports | Accepted |
| [0005](docs/architecture-decisions/0005-policy-and-approval-model.md) | Deterministic policy tiers with human approval | Accepted |
| [0006](docs/architecture-decisions/0006-postgres-as-event-substrate.md) | PostgreSQL as event substrate; no broker in v1 | Accepted |
| [0007](docs/architecture-decisions/0007-offline-fixture-demo-mode.md) | Offline fixture demo mode is the default | Accepted |

---

## Phase 0 — approved decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **LangGraph** for orchestration | Explicit state, conditional routing, checkpointing, retries, and HITL flow control, with a recognized name. Constrained by ADR-0002 so it stays orchestration only. |
| D2 | Phase 1 = **documentation + repository scaffolding** | Session 1 starts on real schemas rather than setup. No application logic, no installs. |
| D3 | **Tiered documentation depth** — 9 deep, 3 initial | Minimizes drift risk between prose and code. No empty filler documents. |
| D4 | **Offline fixture demo mode by default**; live mode opt-in | Determinism is a requirement, not a convenience — see ADR-0007. |
| D5 | Commit incrementally after each milestone; **never push automatically** | The user controls what becomes public and when. |
| D6 | **11 focused working sessions**, not calendar days | Sizing reflects effort, not elapsed time. |
| D7 | Future scenarios stay **architecture + contracts** until the slice works | Rule 2: one complete vertical slice before expanding. |
| D8 | Rename `master` → `main` before the first commit | Done while zero commits existed — clean. |
| D9 | PostgreSQL on host port **55432** | A Homebrew PostgreSQL 16.11 occupies 5432; binding there would silently connect the app to the wrong database. |

---

## Phase 1 — implementation decisions

| # | Decision | Rationale |
|---|---|---|
| D10 | **`uv`** as package manager | Fast, lockfile-based, and sidesteps the Anaconda 3.11 default cleanly. Installed Session 1 with approval. |
| D11 | **No health endpoint in Phase 1** | Keeps "no application logic" literally true. `GET /health` lands Session 1 with its test. |
| D12 | Cost ledger uses **`NUMERIC(12,6)`** | A Haiku call can cost under a hundredth of a cent; two decimals would round the ledger into a lie. |
| D13 | Money as **`NUMERIC(14,2)` + ISO-4217 currency**, never float | Pipeline impact is the number the product is judged on. |
| D14 | Source-mirror tables carry **`is_simulated BOOLEAN NOT NULL DEFAULT TRUE`** | Honesty enforced by schema; the UI badge reads the column. |
| D15 | **No `messaging_send_email` tool** — drafts only | Tier 3. A capability that does not exist cannot be misused, and the demo loses nothing. |
| D16 | **Only 4 of 9 agents are LLM-backed** | Follows from rules 4 and 9; enforced three ways (import-linter, tool boundary, ledger assertion). See ADR-0003. |
| D17 | `analytics_calculate_pipeline_impact` exposed **as an MCP tool** | Lets the analyst agent *request* the calculation without ever performing it. |
| D18 | Detectors take an **injected evaluation timestamp**, never `now()` | Makes detection unit-testable and the demo reproducible. |
| D19 | **Fixture miss raises**, never falls back to the network | A silent fallback would turn an offline test into a billable call, quietly. |
| D20 | Simulated adapters **inject latency and transient failures** | An adapter that never fails does not test the executor's retry path. |
| D21 | Evaluation grader is **deterministic**; LLM judge is ROADMAP | A grader that drifts cannot detect a regression. |
| D22 | Policy engine is **default-deny** for unclassified action types | Fail-closed is the only safe default for a policy engine. |
| D23 | `.gitignore` amended to **stop ignoring `.python-version`** | The pin must be committed for the version to be enforced. |
| D24 | Detector thresholds documented **with rationale** in the event model | Prevents tuning-to-the-fixture; boundary tests at 13 days and 39% enforce it. |

---

## Open questions

Recorded rather than resolved prematurely. Each names when it must be answered.

| # | Question | Answer by |
|---|---|---|
| Q1 | Concrete LangGraph checkpointer — in-memory saver with our tables as durable truth, or a Postgres saver alongside them? | Session 3, when the graph is real. Either way, our tables are authoritative (ADR-0002). |
| Q2 | Should `calculate_impact` run in parallel with `generate_hypotheses`? | Deferred — recorded as known debt. Only worth doing once latency matters. |
| Q3 | Retention policy for `raw_events` | Session 7 or when the table makes local restore slow (ADR-0006). |
| Q4 | Do detector thresholds move to a config table? | After the slice works; recorded as known debt in the scaling roadmap. |
| Q5 | Which integration becomes real first, if any? | Not before the slice is complete, and not without approval. Enrichment is the likely first candidate (ADR-0004). |

---

## Session 11 — contract hardening

**`POLICY_ENGINE_UNAVAILABLE` is its own MCP error code** (owned by ADR-0015; not worth a
separate record). A write tool reached with no policy engine bound used to raise
`MissingPolicyEngineError` out of the dispatcher. Measured before it was changed: over
real stdio the SDK turned that into a protocol-level `MCPError` -- no envelope, no code,
no `integration_status`, and nothing a client could use to distinguish a misconfigured
server from a crashed one. It failed closed, which was right, and said nothing, which was
not.

It is now a typed envelope with `retry: false` and `alternative_route: false`, pinned over
both transports with payload equality. **Deliberately distinct from `POLICY_DENIED`**: a
denial is a decision about the request, this is a deployment fault, and collapsing them
would send an operator looking for a rule that does not exist. The ledger records it as
`DENIED` rather than `ERROR`, because nothing was executed and a generic error could be
read as a partial attempt.

**`rs` is a registered console script.** The README, the demo output, the approval inbox,
and ADR-0018 all print `uv run rs ...` as the exact command to run. Only
`revenue-sentinel` was registered, so on macOS `uv run rs` resolved to `/usr/bin/rs`, a
BSD text-reshaping utility. Registering the alias makes twelve documented commands true
rather than rewriting them all to the long form.

---

## Rejected

Recorded because a rejected option with a reason is more useful than an option nobody
considered.

| Rejected | Reason |
|---|---|
| Microservices from day one | Operational surface with no benefit at this scale; would consume the sessions the slice needs |
| Custom state machine instead of LangGraph | ADR-0002's constraints already prevent framework absorption; owning a runtime is only worth it when the framework fights you |
| Kafka / Redis / Celery | Postgres + outbox is honest at hundreds of events per day (ADR-0006) |
| pgvector / vector DB in v1 | The slice retrieves ~6 evidence items; a `WHERE` clause suffices |
| OTel collector / Jaeger container | Spans are emitted OTel-shaped; no infrastructure needed to prove the design |
| Auth and multi-tenancy in v1 | Adds surface with no interview value on a single-tenant local demo |
| Next.js scaffolded on Day 1 | An empty frontend would rot for eight sessions |
| Nine LLM-backed agents | Would make the impact figure unreproducible — the opposite of the point (ADR-0003) |
| LLM-based policy judgement | Not reproducible, not testable, and directly injection-vulnerable (ADR-0005) |
| Live model calls in the demo path | Network, budget, rate limit, and variance — four ways to fail in an interview room (ADR-0007) |
| A single end-to-end output snapshot instead of per-call fixtures | Tests nothing about intermediate steps and invalidates wholesale on any change |
| Reporting detector precision/recall from one fixture | Would be a fabricated metric |
| A "retry anyway" control on an uncertain action | Looks helpful; duplicates a real-world effect. A retry is reachable only after a human attests the effect did not occur (ADR-0025) |
| Auto-resolving INDETERMINATE actions on a timeout | Converts "we do not know" into "it did not happen" on the basis of elapsed time, and hides exactly the effects worth finding (ADR-0025) |
| `SELECT ... FOR UPDATE` for global budget admission | Holds a row lock across a model call; a hung call would block every concurrent run (ADR-0026) |
| A budget reservation ledger in v1 | A leaked reservation is the INDETERMINATE problem in a second costume, for a budget that has spent $0.000000 (ADR-0026) |
