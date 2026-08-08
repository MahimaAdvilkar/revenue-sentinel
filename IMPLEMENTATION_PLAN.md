# Implementation Plan — 11 Working Sessions

**Status:** AUTHORITATIVE
**Last updated:** 2026-08-01 (Phase 1)

Eleven focused working sessions, not calendar days. **Each session is a milestone gate:
work stops at the end, `PROJECT_STATUS.md` is updated, the repository is verified runnable,
and approval is required before the next session begins** (rules 18 and 20).

Every session below defines: objective, files/modules, acceptance criteria, tests, demo
result, risks, and what must remain unfinished.

---

## Phase 0 — Inspection and proposal ✅ COMPLETE

Repository inspected, architecture proposed, complexity trimmed, slice defined, risks
identified, demo designed, decisions approved.

## Phase 1 — Documentation and scaffolding ✅ COMPLETE

**Objective.** Establish the architecture in writing and the repository skeleton on disk,
before any application code exists.

**Delivered.** 20 documents + 7 ADRs; repository structure with package boundaries;
`pyproject.toml`, `Makefile`, `docker-compose.yml`, `.env.example`, GitHub Actions
workflow, `.python-version`.

**Acceptance.** Documentation created; architecture internally consistent; scaffolding in
place; configuration files valid; capability statuses clear; **no application logic; no
dependencies installed.**

**Unfinished by design.** Everything runnable.

---

## Session 1 — Foundations ✅ COMPLETE

**Objective.** A running database, typed domain models, deterministic synthetic data, and
a test suite — with no agents, no LLM, and no API surface beyond health.

**Outcome.** All eleven acceptance criteria met; 228 tests pass (target was ≥25); three
ADRs added (0008 banded risk factors, 0009 synchronous persistence, 0010 no-`Any`
enforcement). Three documented deviations and two fixed defects are recorded in
[`PROJECT_STATUS.md`](PROJECT_STATUS.md).

**Files / modules**
- `src/revenue_sentinel/core/` — config (Pydantic Settings), structured logging, ID and clock utilities, error types
- `src/revenue_sentinel/domain/` — all Pydantic models and enums from [`docs/data-model.md`](docs/data-model.md)
- `src/revenue_sentinel/db/` — SQLAlchemy models, session factory, repositories
- `src/revenue_sentinel/analytics/pipeline_impact.py` — the deterministic calculator
- `alembic/versions/0001_baseline.py`
- `fixtures/seed/*.json` + `scripts/seed.py`
- `src/revenue_sentinel/api/health.py` — `GET /health` only
- `tests/unit/`, `tests/integration/`, `.importlinter`

**Acceptance criteria**
1. `make setup && make up && make migrate && make seed && make test` succeeds from a clean clone
2. PostgreSQL 16 in Docker on host **55432**; no conflict with the local Homebrew instance
3. One Alembic baseline migration creates all tables; `downgrade` returns to empty
4. Domain models are Pydantic v2 with zero `Any`; `mypy --strict` passes on `domain/` and `analytics/`
5. `ruff check` and `ruff format --check` pass with **no ignores added to silence findings**
6. Seeding is deterministic — same seed, byte-identical rows, asserted by a test
7. The golden scenario (`ACC-1001` / `OPP-2001`) exists in the seeded database and is asserted
8. `import-linter` proves all six boundary rules, including R3 (`analytics/` cannot import `intelligence/`)
9. ≥25 tests pass, including the pipeline-impact arithmetic to the cent
10. CI runs the identical gates on GitHub Actions
11. `PROJECT_STATUS.md` and `CAPABILITY_MATRIX.md` updated

**Tests.** Domain model validation; repository CRUD; seed determinism; golden-scenario
presence; `pipeline_impact` arithmetic including boundaries and zero/negative guards;
migration up/down.

**Demo result.** `make seed` then a `psql` query showing `OPP-2001` at $180,000 with a
14-day activity gap and a +40% usage jump. Plus `pytest` green.

**Risks.** Port 55432 not applied → silent connection to the wrong database. Anaconda
Python 3.11 shadowing 3.12 → subtle dependency issues. Over-modelling the schema before the
workflow proves what it needs.

**Must remain unfinished.** No LLM calls. No MCP server. No agents. No graph. No API beyond
`/health`. No frontend.

---

## Session 2 — Events, signals, incidents ✅ COMPLETE

**Objective.** Turn raw events into a detected stalled opportunity and an open incident.

**Outcome.** All seven acceptance criteria met plus four added during planning; 432 tests
pass (204 new). ADR-0011 added for severity bands. `events/outbox.py` dropped by decision —
no consumer, no storage until Session 6. Deviations recorded in
[`PROJECT_STATUS.md`](PROJECT_STATUS.md).

**Files / modules** — `events/` (envelope, ingest, normalize, dispatcher, outbox),
`signals/` (detector protocol, registry, `stalled_opportunity`), `incidents/` (lifecycle
service, state machine), `api/ingest.py`, `api/incidents.py`

**Acceptance criteria**
1. Ingestion is replay-safe — re-running produces zero duplicate `raw_events`
2. Every normalized event conforms to the canonical envelope with `trust_level="untrusted"`
3. The `stalled_opportunity` detector is pure — evaluation time is injected, never read from the clock
4. Detector fires on `OPP-2001` and on nothing else in the seed set
5. `dedupe_key` prevents a second incident for the same condition
6. Incident lifecycle transitions are persisted and illegal transitions are rejected
7. Seven additional detectors are registered as contracts with no implementation, labelled ROADMAP

**Tests.** Envelope validation; normalizer per source; detector positive/negative/boundary
cases (13 days = no fire, 39% growth = no fire); dedupe; illegal lifecycle transitions;
replay safety.

**Demo result.** `make ingest` → `INC-001` visible via `GET /incidents`, with the signal
that produced it.

**Risks.** Detector thresholds tuned to make the fixture pass rather than to be defensible.
Over-general normalizer before the second source type exists.

**Must remain unfinished.** No investigation. No agents. No LLM. No MCP.

---

## Session 3 — Investigation graph ✅ COMPLETE

**Objective.** The first LLM-backed agents, running inside the LangGraph state machine,
producing evidence, hypotheses, and a deterministic impact figure.

**Outcome.** All eight acceptance criteria met plus five added during planning; 548 tests
pass (116 new); **$0 spent and no live API call made**. ADR-0012 (checkpointer, closing
ADR-0002's deferred question) and ADR-0013 (hand-authored fixtures, qualifying ADR-0007).
Deviations and the unexercised live path recorded in [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

**Files / modules** — `orchestration/` (graph definition, state, checkpointing, transition
recorder), `agents/planner.py`, `agents/researcher.py`, `agents/analyst.py`,
`intelligence/` (LLM client port, `AnthropicLLMClient`, `FixtureLLMClient`, prompt
templates, structured-output schemas), `fixtures/llm/`

**Acceptance criteria**
1. Graph runs `plan_investigation → collect_evidence → generate_hypotheses → calculate_impact`
2. Every transition written to `workflow_transitions` **before** the next node runs
3. Every LLM call returns schema-validated structured output — no free-text parsing anywhere
4. ≥2 hypotheses, each citing an `evidence_id` that exists in state; a fabricated citation fails validation
5. Impact computed by `analytics/`, never by a model; `impact_assessments.inputs` records every input
6. `DEMO_MODE=fixture` runs the full path with no network; a fixture miss raises rather than falling back
7. Untrusted content appears only inside delimited `<evidence>` blocks
8. Node bodies are thin — no domain logic inside the graph (ADR-0002)

**Tests.** Each agent as a pure function with a stubbed LLM; schema validation rejects
malformed and fabricated-citation output; transition ordering is gapless; fixture-miss
raises; graph resumes from checkpoint; `analytics/` cannot import `intelligence/`.

**Demo result.** `make investigate INCIDENT=INC-001` prints the plan, six evidence items,
two cited hypotheses, and **$108,000 weighted / $32,130 at risk**.

**Risks.** LangGraph absorption — logic creeping into nodes. Prompt iteration consuming the
session. Checkpointer semantics conflicting with our transition table (the open question
from ADR-0002 is resolved here).

**Must remain unfinished.** No MCP server — evidence comes from repositories directly this
session. No strategy. No policy. No execution.

---

## Session 4 — GTM MCP server ✅ COMPLETE

**Objective.** Replace direct repository access with the real MCP tool layer.

**Outcome.** All nine acceptance criteria met; **730 tests pass (182 new)**. ADR-0014 added
for the sync/async boundary. All 15 tools implemented; **both transports IMPLEMENTED** —
stdio verified against a real subprocess. Evidence parity is **byte-equivalent** and fixture
digests are unchanged. Every integration remains **SIMULATED**. The four write tools are
registered but **unwired from the graph**, and none has been executed. Deviations — MCP SDK
2.0 rather than 1.1, a latent `RepositoryEvidenceSource` contract defect, and a broken
`make mcp` target — are recorded in [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

**Files / modules** — `mcp/` (errors, envelope, schemas, registry, gate, dispatcher, ledger,
context), `mcp/tools/*.py` (15 tools), `mcp/server.py` + `scripts/mcp_server.py` (stdio),
`mcp/client.py` (in-process + `AsyncBridge`), `integrations/ports/*.py`,
`integrations/simulated/*.py`, `integrations/status.py`, `governance/stub.py`,
`orchestration/mcp_evidence_source.py`

**Acceptance criteria**
1. All 15 tools implemented with strict JSON Schema (`additionalProperties: false`)
2. Write tools cannot reach their adapter without a policy decision (stubbed ALLOW this session)
3. Every adapter declares `INTEGRATION_STATUS = "SIMULATED"`, stamped on every tool result
4. Every adapter docstring contains a "What changes when this becomes real" section
5. All seven typed error codes implemented; `POLICY_DENIED` instructs the agent not to reroute
6. In-process client for tests, stdio server for the demo — identical handlers
7. Every call writes a `tool_calls` row with trace and span IDs
8. Simulated adapters inject realistic latency and transient failures (ADR-0004)
9. Research Agent now gathers evidence exclusively through MCP

**Tests.** Per-tool schema validation, happy path, and error path; write tools blocked
without a decision; adapters return deterministic fixtures; transient-failure retry;
in-process and stdio produce identical results.

**Demo result.** ✅ `make mcp` runs the stdio MCP server; `make investigate` produces the
same output as Session 3 — 6 evidence items, 2 hypotheses, $108,000.00 weighted and
$32,130.00 at risk — now sourced through MCP tool calls visible in `tool_calls`.

**Risks — as they landed.** Fifteen tools was indeed the largest surface, and it held. MCP
transport did eat time: the SDK resolved to 2.0 rather than 1.1, which moved several
attribute names and made the low-level `Server` the right choice over the ergonomic
wrapper. Tool arguments did not broaden — every one is a frozen Pydantic model with
`extra="forbid"`.

**Remained unfinished, by design.** Real policy engine (stubs only, and **the stub was
never used to demonstrate a write**). Write tools registered but **unwired from the graph**.
`BUDGET_EXCEEDED` defined with **no producer until Session 7**. No `messaging_send_email`,
and no send method on `MessagingPort`. No strategy, execution, retries, cost governance, or
frontend. **No real credentials, external integrations, paid calls, or live LLM calls —
$0 spent.**

**Open question carried to Session 5.** The client-visible shape of a write refused over
stdio for want of a policy engine is not yet pinned by a subprocess test. The dispatcher-level
guarantee is proven in-process.

---

## Session 5 — Strategy and policy ✅ COMPLETE

**Objective.** Ranked interventions, and the real governance layer.

**Outcome.** All nine acceptance criteria met; **789 tests pass (56 new)**. ADR-0015
added for policy as a pure function. Migration `0004` widened `interventions.action_type`
to `proposed_action`, so a **refused** proposal can be recorded rather than dropped. The
golden scenario yields **1 ALLOW, 1 REQUIRE_APPROVAL, 1 DENY** — and **nothing executes**:
the four write tools remain unwired, `run_investigation` still binds `policy=None`, and
no `action_records` row is written. Money figures unchanged at $108,000.00 / $32,130.00.
$0 spent; the strategy fixture is hand-authored (ADR-0013).

**Files / modules** — `agents/strategist.py`, `analytics/intervention_scoring.py`,
`governance/policy_engine.py`, `governance/rules.py`, `governance/tiers.py`,
`governance/approvals.py`, `agents/policy_agent.py`

**Acceptance criteria**
1. Exactly 3 interventions, ranked by a **tested deterministic** composite score
2. The LLM drafts; the scorer ranks — ranking is never model output
3. Policy engine is a pure function; same input, same decision, always
4. All four tiers implemented; "material CRM change" matches the definition in the security model exactly
5. **Default-deny** for unclassified action types, with an explicit test
6. Ambiguous classification escalates to the higher tier
7. Every decision records `matched_rules` and a human-readable reason
8. Approval requests created with `expires_at`; no self-approval possible
9. The golden scenario yields 1 ALLOW, 1 REQUIRE_APPROVAL, 1 DENY

**Tests.** Scoring determinism and ordering; every tier classification; material-vs-not
boundary cases; default-deny; escalation on ambiguity; approval request creation, expiry,
and self-approval rejection.

**Demo result.** ✅ `make investigate INCIDENT=INC-001`:

```
  INTERVENTIONS (3 ranked -- drafted by a model, ordered by analytics/)
    1. Book a proposal review with the economic buyer
       action crm_task   expected 16065.00 USD   score 4.96
       POLICY ALLOW             tier 1   rules: tier1:internal-reversible
    2. Send the champion a usage-insight summary
       action email_draft   expected 16065.00 USD   score 2.48
       POLICY REQUIRE_APPROVAL  tier 2   rules: tier2:customer-facing
    3. Email the buying committee directly to force a decision
       action send_email_direct   expected 16065.00 USD   score 1.24
       POLICY DENY              tier 3   rules: tier3:prohibited-capability

  Nothing was executed. Session 5 decides; execution arrives in Session 6.
```

The model drafted **four**; the scorer dropped the lowest and kept three. Which three is
`analytics/`'s call, and a test asserts the dropped one is absent — otherwise the ranking
would be untested in the only way that matters.

**Risks — as they landed.** Tier boundaries did not feel arbitrary because they were
transcribed from `docs/security-model.md` §3 rather than invented, and a test compares
the two. Scoring weights were the real risk: the composite is normalised by weighted
value so it ranks the *intervention* rather than restating which deal is bigger, and
tier 3 is scored far above tier 2 so a prohibited action can never out-rank a permitted
one on expected value alone.

**Remained unfinished, by design.** Nothing executes. No approval UI and no approval
endpoints — `governance/approvals.py` is reachable only from tests and from persistence.
No retries, no cost governance, no evaluation, no frontend. Every integration still
SIMULATED. `$0` spent.

---

## Session 6 — Execution and audit ✅ COMPLETE

**Outcome.** **838 tests pass (49 new).** ADRs 0016–0018 added and ADR-0012 amended.
Migrations `0005` and `0006`. `make demo` runs the whole scenario offline for `$0`.

**Deviation from the approved plan, taken with approval:** LangGraph `interrupt()` and
`PostgresSaver` were **not** adopted. Building the execution phase showed the checkpointer
would carry state nothing reads — by the time the workflow pauses, everything needed to
resume is already committed to business tables. The dependency was installed, evaluated,
and removed; ADR-0016 records the analysis and the three triggers that would reverse it.
**This is application-level resume, not LangGraph durable interrupt/resume.**

**Also true:** exactly-once is not claimed (at-least-once with an explicit
`INDETERMINATE` state); approvals are CLI-only with a *claimed* identity and no
authentication; `crm_update_opportunity` stays unreachable; `messaging_send_email` does
not exist; every executed result is SIMULATED.


**Objective.** Close the loop — actions actually happen, exactly once, with a full trail.

**Files / modules** — `execution/executor.py`, `execution/idempotency.py`,
`execution/retry.py`, `execution/outbox.py`, `agents/executor_agent.py`,
`observability/audit.py`, `api/approvals.py`

**Acceptance criteria**
1. `idempotency_key = sha256(run_id | intervention_ref | action_type | target_ref)`, UNIQUE in the database
2. Replaying a completed run creates **zero** new actions and returns the originals
3. Tier 1 CRM task auto-executes with no approval request
4. Tier 2 email draft blocks; the graph interrupts and the process may exit
5. Approving via the API resumes the run from checkpoint and creates the draft
6. Rejection closes the incident `CLOSED_REJECTED` with the note preserved
7. Bounded exponential backoff; exhausted retries mark `FAILED` and emit an audit event — never silent
8. Outbox: action record and outbox entry written in one transaction
9. Every action traces to a policy decision or an approval

**Tests.** Idempotency under replay and concurrency; interrupt and resume across a process
restart; approve, reject, and expire paths; retry exhaustion; outbox recovery after a
simulated crash; no orphan actions.

**Demo result.** **The full vertical slice.** Ingest → incident → investigate → strategize →
policy → auto-task → approval gate → approve → draft → re-run with no duplicates.

**Risks.** Interrupt/resume is the most intricate mechanism in the system. Concurrency
races on idempotency. This is the highest-risk session in the plan.

**Must remain unfinished.** No cost tracking. No evaluation. No dashboard. No frontend.

---

## Session 7 — Cost and observability

**Objective.** Make every dollar and every span visible.

**Files / modules** — `observability/tracing.py`, `observability/ledger.py`,
`agents/cost_governor.py`, `intelligence/routing.py`, `intelligence/pricing.py`,
`api/timeline.py`

**Acceptance criteria**
1. Pre-call budget check at all three scopes; a projected breach refuses the call
2. `model_calls` records input, output, **and cache** tokens separately
3. `cost_entries` uses `NUMERIC(12,6)` and records `pricing_version`
4. Model routing is per call site, config-driven; default `claude-opus-5`
5. Prompt caching: frozen system prompt, deterministic tool ordering, breakpoint on the last stable block
6. An integration test asserts `cache_read_input_tokens > 0` on the second call of a run
7. Non-monetary ceilings enforced (model calls, tool calls, node executions, wall clock)
8. Every span carries `trace_id`, `span_id`, `parent_span_id`, `run_id`, `incident_id`
9. `GET /incidents/{ref}/timeline` returns the full correlated trace in one query

**Tests.** Budget enforcement at each scope; hard-stop halts the run; cost arithmetic;
pricing version isolation; cache-hit assertion; each non-monetary ceiling; span correlation.

**Demo result.** `make demo` prints a cost breakdown — total, per model call, cache hit
rate — and the incident timeline as ordered JSON.

**Risks.** Cache invalidation from an accidentally dynamic system prompt — silent and
expensive. Pricing drift against the published table.

**Must remain unfinished.** No OTLP exporter (ROADMAP). No dashboard.

---

## Session 8 — Evaluation and security

**Objective.** Prove the system behaves correctly, and prove injection cannot escalate.

**Files / modules** — `evaluation/rubric.py`, `evaluation/checks/*.py`,
`evaluation/runner.py`, `agents/evaluation_agent.py`, `fixtures/injection/*`,
`fixtures/expected/INC-001.json`, `tests/evaluation/`

**Acceptance criteria**
1. All 15 rubric checks from [`docs/evaluation-strategy.md`](docs/evaluation-strategy.md) implemented and passing
2. `no_llm_arithmetic` queries the ledger and proves no model call is attributed to a deterministic node
3. `hypotheses_cite_real_evidence` fails on a fabricated-citation fixture
4. `replay_produces_no_duplicates` passes
5. All six injection cases: workflow completes, **no unauthorized action**, attempt logged
6. `POLICY_DENIED` does not trigger an alternative-tool retry
7. Secret-scan across source, fixtures, and git history is clean
8. Full security review checklist from the security model completed and recorded
9. **No test skipped, xfailed, or weakened to pass** (rule 13)

**Tests.** The eval suite is the test. Plus negative tests that deliberately break each
invariant and assert the corresponding check fails.

**Demo result.** `make eval` — 15/15 rubric checks pass, 6/6 security cases pass, with a
printed report.

**Risks.** Discovering a real policy hole late. Injection cases that are too easy and prove
nothing. Time pressure tempting a weakened assertion — which rule 13 forbids absolutely.

**Must remain unfinished.** No LLM judge (ROADMAP). No frontend.

---

## Session 9 — Dashboard

**Objective.** The professional surface — read-only over already-final APIs, plus the one
interactive flow.

**Files / modules** — `apps/web/` (Next.js + TypeScript), executive overview, incident
queue, incident detail (timeline, evidence, hypotheses, impact, interventions), approval
inbox, shared API client with generated types

**Acceptance criteria**
1. All views read from existing endpoints — **no backend changes this session**
2. SIMULATED badges rendered from `is_simulated` / `INTEGRATION_STATUS`, never hardcoded
3. Incident detail shows the complete timeline: transitions, decisions, tool calls, model calls, audit events
4. Hypotheses link to the evidence they cite
5. Impact shows the figure **and its inputs**, so it can be verified on screen
6. Approval inbox is the only interactive surface: approve and reject with a note
7. Approving resumes the workflow and the UI reflects the new state
8. TypeScript strict mode; no `any`; API types generated from the OpenAPI schema

**Tests.** Component tests for the approval flow; type generation is current; an end-to-end
approval exercised against a live local API.

**Demo result.** The five-minute walkthrough runs in the browser, beats 0:00 through 4:00.

**Risks.** The largest scope in the plan and the most likely to overrun. Design polish
consuming time budgeted for correctness.

**Contingency.** If time is lost, cut Session 10's cost and evaluation UI — **never** the
audit trail or the approval inbox.

**Must remain unfinished.** Cost center, evaluation center, integration catalog.

---

## Session 10 — Remaining surfaces, CI, release readiness

**Objective.** Complete the dashboard and harden the build.

**Files / modules** — cost center, evaluation center, integration catalog,
`.github/workflows/ci.yml` (full matrix), `Makefile` (demo targets), `scripts/record.py`

**Acceptance criteria**
1. Cost center: period spend vs budget, per-incident cost, model mix, cache effectiveness
2. Evaluation center: latest suite result, per-check expected vs actual, security results
3. Integration catalog: every integration with its IMPLEMENTED / SIMULATED / SCAFFOLDED / ROADMAP status
4. CI runs every gate on push and PR, offline, with no API key
5. Fixture-freshness check fails when a prompt template changes without regenerated fixtures
6. `make demo` runs the complete scenario offline, end to end
7. Live smoke test exists as a manual, opt-in target
8. Fresh clone verified: install → run → test → demo

**Tests.** Full suite green in CI; fresh-clone verification performed and recorded.

**Demo result.** `make demo` end to end, plus the complete dashboard.

**Risks.** CI environment differences from local. Fixture staleness discovered late.

**Must remain unfinished.** No cloud deployment (rules 16 and 20).

---

## Session 11 — Portfolio packaging

**Objective.** Make the work legible to someone who has five minutes and no context.

**Files / modules** — `README.md` (final), `CASE_STUDY.md`, `docs/screenshots/`,
`docs/demo-recording-plan.md`, `docs/interview-talking-points.md`, final
`PROJECT_STATUS.md`, `CAPABILITY_MATRIX.md`, `RISKS.md`, `docs/scaling-roadmap.md`

**Acceptance criteria**
1. README: what it is, what is real vs simulated, how to run it, architecture at a glance
2. CASE_STUDY: problem, approach, key decisions, what was learned, what was left out and why
3. All ten Mermaid diagrams render correctly on GitHub
4. Screenshots of every dashboard surface
5. Demo recording plan matching the five-minute script
6. Interview talking points: the four-of-nine-agents claim, the policy layer, idempotency, cost, and evaluation
7. **Limitations stated plainly** — no overstatement of what is real (rule 5)
8. Every document consistent with the final code (rules 11 and 15)
9. Repository runnable from a fresh clone

**Tests.** Full suite green. Every documented command executed and verified.

**Demo result.** The complete five-minute demo, recorded.

**Risks.** Documentation drift accumulated across ten sessions surfacing all at once.
Overclaiming under the temptation to make it sound more impressive.

**Must remain unfinished.** Everything on the roadmap, clearly labelled as such.

---

## Cross-session standing rules

| Rule | Applies |
|---|---|
| Stop at each milestone and wait for approval | Every session |
| Update `PROJECT_STATUS.md` before stopping | Every session |
| Update architecture docs in the same commit as the change | Every session |
| Repository runnable at end of session | Every session |
| No test skipped or weakened to pass | Every session |
| No paid cloud resources without approval | Every session |
| Commit incrementally; never push automatically | Every session |
