# Project Status

**Last updated:** 2026-08-08
**Current milestone:** Session 11 — Hardening and close-out ✅ **COMPLETE**
**Next milestone:** none. v1 is closed.

---

## Where the project actually is

**The investigation runs through a real MCP server, offline and for free.** Seed → ingest →
investigate produces a plan, six evidence items, two cited hypotheses, and **$108,000.00
weighted / $32,130.00 at risk** — with no API key, no network, and no money spent. As of
Session 4 the evidence arrives through **MCP tool calls**, not repository reads, and the
figures did not move by a cent.

| Question | Answer |
|---|---|
| Can you run it? | Yes — `make setup && make up && make migrate && make seed && make ingest && make investigate` |
| Can you run the tests? | Yes — **1,056 backend, 0 skipped, 0 xfailed**, plus **60 frontend**. One `live` test exists and is deselected by default |
| **Can an uncertain effect be resolved?** | **Yes, as of Session 11.** `rs reconcile` — human-attested, evidence mandatory, two outcomes, no retry button (ADR-0025) |
| **Is there a dashboard?** | **Yes.** Seven screens — overview, incident queue, incident detail, approval inbox, **cost centre, evaluation centre, integration catalogue**. `make web` |
| **Does a fresh checkout work?** | **Yes, verified in Session 10** — install, migrate, seed, demo, eval, 1011 backend tests, and the frontend build all pass from a clone-equivalent tree |
| **Does CI gate the frontend?** | **Yes.** Contract freshness, typecheck, build, and tests — with the offline scan running against the built output |
| Can you approve in the browser? | **No, deliberately.** The inbox shows the CLI command. There is no auth, so a button would imply accountability that does not exist (ADR-0022) |
| Does detection work? | Yes — 1 signal across 15 opportunities, `INC-001` at `HIGH` |
| Does the investigation work? | Yes — **6 nodes, 7 transitions**, 6 evidence items, 2 hypotheses, 3 ranked interventions |
| **Is the MCP server real?** | **Yes.** 15 tools, both transports. `make mcp` runs a spec-compliant stdio server; a test drives it as a real subprocess |
| **Are the integrations real?** | **No. Every one is SIMULATED**, and every tool result says so — over both transports |
| Are the money figures right? | Yes — computed by `analytics/`, asserted to the cent |
| **Is the policy engine real?** | **Yes.** Four tiers, default-deny, escalation on ambiguity, every decision recording its rules. A pure function (ADR-0015) |
| Can the system write to anything? | **No.** 4 write tools are registered but unwired; the graph binds no policy engine, so a write would raise |
| **Does anything execute?** | **Yes, as of Session 6** — one SIMULATED CRM task automatically, one SIMULATED email **draft** after a human approves. Nothing is ever sent |
| Does `make demo` work? | **Yes** — offline, `$0`, end to end, and it proves a re-run creates zero duplicate effects |
| Is resume restart-safe? | Yes — proven by destroying the session and engine and resuming against a fresh one (ADR-0016) |
| Is it exactly-once? | **No, and not claimed.** At-least-once with an explicit `INDETERMINATE` state requiring human reconciliation (ADR-0017) |
| Are approvals authenticated? | **No.** `--as` is a *claimed* identity. There is no authentication anywhere (ADR-0018) |
| **Are budgets enforced?** | **Yes, before the spend.** `BUDGET_EXCEEDED` fires before the client is reached — proven by a counting fake that records zero calls (ADR-0019) |
| **Does it evaluate itself?** | **Yes.** `make eval` — workflow 15/15, injection 6/6, invariants 1/1, bypass 5/5. Deterministic, `$0.000000`, **no LLM judge** |
| Is the evaluator trustworthy? | Every one of the 15 checks has a **negative test** proving it can fail. A rubric nobody has seen fail is one nobody knows works |
| What has it cost? | **$0.000000**, printed unrounded. Fixture mode consumes zero tokens, so that figure is the truth rather than a rounding |
| Is it replay-safe? | Ingestion yes. Execution yes, by idempotency key. **Re-investigating a completed incident is still refused** — resume is not replay. |
| **Has this system ever called a model?** | **No. Not once.** |
| Are the LLM fixtures real? | **No — hand-authored, not recorded.** See ADR-0013. |

---

## Milestone log

### Phase 0 / Phase 1 ✅
Architecture, 20 documents, 7 ADRs, scaffolding. No application code.

### Session 1 — Foundations ✅
`core/`, `domain/` (29 models), `analytics/pipeline_impact.py`, `db/` (29 tables),
Alembic baseline, deterministic seeder, `GET /health`. 228 tests. ADRs 0008–0010.

### Session 2 — Events, signals, incidents ✅
SIMULATED source feed, replay-safe ingestion, normalization, the `stalled_opportunity`
detector, 7 ROADMAP contracts, severity bands, incident lifecycle, three endpoints.
432 tests. ADR-0011.

### Session 3 — Investigation graph ✅

**Delivered**

| Group | Detail |
|---|---|
| `intelligence/` | LLM port, prompt digest, frozen prompts with escaped evidence blocks, structured-output schemas, fixture client, live client (unexecuted) |
| `agents/` | `EvidenceSource` port, planner, researcher, analyst, citation gate |
| `orchestration/` | State, 4 thin nodes, graph with transition-recording wrapper, persistence, runner |
| `alembic/0003` | `model_calls.is_replay` |
| `fixtures/llm/` | 3 hand-authored fixtures |
| `tests/` | 116 new — 548 total |
| Docs | ADR-0012 (checkpointer), ADR-0013 (hand-authored fixtures) |

**Acceptance — all thirteen criteria met**

| # | Criterion | Result |
|---|---|---|
| 1 | Graph runs the four nodes in order | ✅ `plan → evidence → hypotheses → impact` |
| 2 | Transitions written **before** the next node; gapless | ✅ 5 rows, sequence 0–4, chain verified |
| 3 | Every LLM call schema-validated; no free-text parsing | ✅ validation happens inside the client |
| 4 | ≥2 hypotheses citing real evidence; fabrication persists nothing | ✅ run aborts, tables stay empty |
| 5 | Impact from `analytics/`; inputs recorded | ✅ `computed_by = deterministic`, `model_call_id IS NULL` |
| 6 | Fixture mode runs with **no network**; a miss raises | ✅ full run with `socket.socket` refusing |
| 7 | Untrusted content only inside delimited `<evidence>` blocks | ✅ tag-forgery payload contained |
| 8 | Node bodies thin — no domain logic, no persistence | ✅ AST-asserted: no `db` import, ≤6 statements |
| 9 | Migration `0003` up and down clean; no drift | ✅ `alembic check` reports nothing pending |
| 10 | **Zero dollars spent** | ✅ no live call made, `make record` never run |
| 11 | Incident advances `TRIAGED → INVESTIGATING → ANALYZED` | ✅ audit row per transition |
| 12 | All 432 existing tests still pass | ✅ unmodified |
| 13 | Docs updated | ✅ this commit |

**Demo result**

```
make investigate INCIDENT=INC-001        # DEMO_MODE=fixture, no key, no network

  PLAN (5 steps)          crm_get_opportunity, crm_list_account_activities,
                          product_get_usage_summary, engagement_get_email_activity,
                          support_get_open_issues
  EVIDENCE (6 items)      EV-001..EV-006 across 4 source systems
  HYPOTHESES (2)          H1 conf 0.72 cites EV-002, EV-004
                          H2 conf 0.41 cites EV-005, EV-006
  IMPACT                  pipeline 180000.00   weighted 108000.00
                          stall risk 0.3500    gross 37800.00
                          usage offset 0.1500  AT RISK 32130.00 USD
```

### Session 4 — GTM MCP server ✅

**Delivered**

| Group | Detail |
|---|---|
| `integrations/ports/` | 6 Protocols (crm, product, engagement, support, enrichment, messaging). **`MessagingPort` has no send method** |
| `integrations/simulated/` | 6 adapters, each declaring `INTEGRATION_STATUS = "SIMULATED"` and a substantive "What changes when this becomes real" section |
| `integrations/status.py` | `status_of()` — an adapter that does not declare a status **raises**; there is no default |
| `integrations/simulated/behaviour.py` | Deterministic latency and scripted failure injection, **inert by default** |
| `mcp/` | errors, envelope, schemas, registry, gate, dispatcher, ledger, context |
| `mcp/tools/` | All **15** tools, strict Pydantic args (`extra="forbid"` → `additionalProperties: false`) |
| `mcp/client.py` | Synchronous `McpClient` port, `InProcessMcpClient`, `AsyncBridge` (ADR-0014) |
| `mcp/server.py` + `scripts/mcp_server.py` | Low-level MCP `Server` and the stdio entry point behind `make mcp` |
| `governance/stub.py` | `StubPolicyEngine` / `DenyAllPolicyEngine` — **for tests only**; never used to demonstrate a write |
| `orchestration/mcp_evidence_source.py` | The evidence port, MCP-backed. Wired into `run_investigation` |
| `tests/` | **182 new — 730 total** |
| Docs | **ADR-0014** (sync/async boundary) |

**Acceptance — all nine criteria met**

| # | Criterion | Result |
|---|---|---|
| 1 | 15 tools with `additionalProperties: false` | ✅ asserted per tool, in-process **and as received over stdio** |
| 2 | Write tools cannot reach an adapter without a policy decision | ✅ no engine bound → raises; denied write verified against a spy adapter |
| 3 | Every adapter declares `INTEGRATION_STATUS = "SIMULATED"`, stamped on every result | ✅ survives both transports |
| 4 | Every adapter docstring has "What changes when this becomes real" | ✅ named APIs, auth, rate limits, differing fields |
| 5 | Seven typed error codes; `POLICY_DENIED` forbids rerouting | ✅ `retry=False, alternative_route=False`, tested |
| 6 | In-process client and stdio server, identical handlers | ✅ both delegate to `dispatcher.dispatch`; payload equality tested |
| 7 | Every call writes a `tool_calls` row with trace and span IDs | ✅ success, typed error, **and denial** |
| 8 | Deterministic simulated latency and failures | ✅ scripted, not random; disabled by default |
| 9 | Research Agent gathers evidence exclusively through MCP | ✅ `McpEvidenceSource`; parity **byte-equivalent** |

**The stdio proof**

```
handshake OK | server: revenue-sentinel-gtm | protocol: 2025-11-25
tools via stdio: 15
additionalProperties via stdio: False
stdio call ok: True | status: SIMULATED | name: Northwind Logistics
stdio NOT_FOUND: NOT_FOUND | is_error: True
```

A real subprocess over real pipes, not a simulation of a transport. 11 automated tests in
`tests/integration/test_transport_parity.py` hold that claim to account.

### Session 5 — Strategy and policy ✅

**Delivered**

| Group | Detail |
|---|---|
| `governance/` | `outcomes.py` (the shared `PolicyOutcome`), `tiers.py`, `rules.py`, `policy_engine.py`, `approvals.py` |
| `analytics/intervention_scoring.py` | Banded recovery/effort tables, tier-derived risk, normalised composite, total ordering |
| `agents/strategist.py` | Drafts 3-5 interventions; **supplies no numbers and no ordering** |
| `agents/policy_agent.py` | Deterministic; one decision per intervention |
| `orchestration/` | Two new nodes (`draft_interventions`, `evaluate_policy`), state fields, governance persistence |
| `alembic/0004` | `interventions.action_type` widened to `proposed_action` |
| `fixtures/llm/` | 1 hand-authored strategy fixture — 4 total |
| `tests/` | **56 new — 789 total** |
| Docs | **ADR-0015** (policy as a pure function) |

**Acceptance — all nine criteria met**

| # | Criterion | Result |
|---|---|---|
| 1 | Exactly 3 interventions, ranked by a tested deterministic score | ✅ model drafted 4; scorer kept 3 |
| 2 | The LLM drafts; the scorer ranks | ✅ `analytics/` cannot import `intelligence/` or `agents/` (R3), asserted again per-module by AST |
| 3 | Policy engine is a pure function | ✅ no I/O, no clock; 25 identical evaluations asserted |
| 4 | All four tiers; "material CRM change" matches the security model exactly | ✅ set transcribed and compared by test |
| 5 | **Default-deny** for unclassified actions | ✅ unknown action, unknown field, and *no* field all deny |
| 6 | Ambiguity escalates to the higher tier | ✅ `max()`; mixed field update → tier 2; unclassified field → tier 3 |
| 7 | Every decision records `matched_rules` and a readable reason | ✅ asserted on all three golden rows |
| 8 | Approvals with `expires_at`; no self-approval | ✅ plus expiry evaluated **on read**, not by a sweeper |
| 9 | Golden scenario: 1 ALLOW, 1 REQUIRE_APPROVAL, 1 DENY | ✅ and `action_records` is empty |

### Session 6 — Execution and audit ✅

**Delivered**

| Group | Detail |
|---|---|
| `execution/` | `idempotency`, `authorization`, `executor`, `retry`, `arguments`, `service`, `policy_binding` |
| `governance/approval_service.py` | Lookup by `APR-001`, effective-status listing |
| `cli.py` | `approvals`, `approve`, `reject`, `resume` |
| `scripts/demo.py` | `make demo` — the whole scenario, offline, `$0` |
| `alembic/0005` | `approval_requests.requested_by` real column + backfill, `approval_ref` sequence |
| `alembic/0006` | `authorized_by` FK, `approval_request_id`, `interventions.target_ref`, `ActionStatus.INDETERMINATE` |
| `tests/` | **49 new — 838 total** |
| Docs | **ADR-0016**, **ADR-0017**, **ADR-0018**, and an **amendment to ADR-0012** |

**How resume actually works — and what it is not**

> **This is not LangGraph durable interrupt/resume.** There is no `interrupt()` call and
> no `PostgresSaver`. `langgraph-checkpoint-postgres` was installed, evaluated, and
> **removed**.
>
> Approval resume is **application-level resume over persisted business state**. By the
> time the workflow pauses, everything needed to continue is committed:
> `workflow_runs`, `interventions`, `policy_evaluations`, `approval_requests`,
> `action_records`, `workflow_transitions`, `audit_events`. `resume_investigation` reads
> those rows and continues the execution phase. No investigation node re-runs, and no
> model call site is exercised.
>
> `InMemorySaver` remains for the analytical graph, which has no human interrupt.
> ADR-0012 is **amended, not superseded**: its "revisit when" trigger fired and the
> review concluded durable *business* state was the right remedy. See ADR-0016.

**Acceptance — all criteria met**

| # | Criterion | Result |
|---|---|---|
| 1 | Tier 1 executes automatically | ✅ one `SUCCEEDED` action record, stamped `SIMULATED` |
| 2 | Tier 2 pauses; nothing drafted before approval | ✅ run `INTERRUPTED`, incident `AWAITING_APPROVAL` |
| 3 | Approve + resume creates exactly one unsent draft | ✅ |
| 4 | Re-running produces zero new effects | ✅ stored results returned, adapter not called |
| 5 | A denied action never executes, even with a forged **APPROVED** row | ✅ |
| 6 | Execution re-evaluates policy; drift fails closed | ✅ `PolicyDriftError` |
| 7 | Only `RATE_LIMITED` / `ADAPTER_ERROR` retry, max 3 | ✅ every attempt in `tool_calls` |
| 8 | Resume survives the runtime being destroyed | ✅ new engine, new session, fresh connections |
| 9 | Migrations 0005/0006 clean; no drift | ✅ |
| 10 | Every execution result carries `integration_status = "SIMULATED"` | ✅ |
| 11 | No `messaging_send_email`; `crm_update_opportunity` unreachable | ✅ |
| 12 | `make demo` end to end, offline, `$0` | ✅ |

### Session 7 — Cost governance ✅

**Delivered**

| Group | Detail |
|---|---|
| `cost/pricing.py` | Pure, versioned price table. Unpriced model **raises** |
| `cost/routing.py` | Frozen call-site → model table. Unrouted site **raises** |
| `cost/estimation.py` | Deterministic, conservative input estimate — admission control only |
| `cost/governor.py` | Worst-case reservation, scopes ANDed, 12/30 call ceilings |
| `cost/client.py` | `BudgetedLLMClient` — the gate, ahead of the client call |
| `cost/ledger.py` | `$0.000000` entry per call; exact budget reconciliation |
| `cost/timeline.py` | Merges `model_calls`, `tool_calls`, `cost_entries`, `audit_events` |
| `cost/summary.py` | Run totals at microdollar precision |
| `cli.py` | `rs cost INC-001 [--timeline]` |
| `alembic/0007` | Budget precision widened to `NUMERIC(12, 6)` |
| `tests/` | **57 new — 895 total** |
| Docs | **ADR-0019**, **ADR-0020** |

**The enforcement path** — the order is the contract, and it is a decorator so it cannot
be partially applied:

```
route → call ceilings → input estimate → worst-case check
      → BUDGET_EXCEEDED raised HERE, before the client
      → model call → actual usage → cost entry → consumed_usd
```

**Two things this does not claim.** The estimator is admission control, **never billing
truth** — provider tokenization differs and only actual returned usage is recorded.
And budgets are **not concurrency-safe across runs**: read-then-call is sound only
because model calls are serialized within a run (ADR-0009). Two concurrent runs sharing a
`GLOBAL` budget can race. The CLI and demo both print that caveat.

### Session 8 — Evaluation ✅

**Delivered**

| Group | Detail |
|---|---|
| `evaluation/rubric.py` | 15 workflow checks, each decided from persisted rows |
| `evaluation/security.py` | 6 named injection cases, 1 cross-cutting invariant, 5 bypass checks |
| `evaluation/service.py` | evaluate → persist → render, one implementation |
| `scripts/evaluate.py` | `make eval`, non-zero exit on failure |
| `tests/evaluation/` | 55 tests — positives, the full negative corpus, append-only audit |
| Docs | **ADR-0021** |

**Result:** workflow rubric **15/15** · injection corpus **6/6** · security invariants
**1/1** · policy bypass **5/5** · overall **PASS** · **LLM judge: NOT USED** · evaluation
cost **$0.000000**.

**Why this is worth trusting.** Every check has a negative test that breaks the property
it guards and asserts the check fails — a check with an inverted comparison would sail
through a green run otherwise. Where a schema constraint makes the strongest corruption
**unrepresentable** (`UNIQUE (idempotency_key)`, the `authorized_by` foreign key,
`hypothesis_evidence`'s keys), the test asserts the constraint and documents why, rather
than weakening a real guarantee to manufacture a cosmetic failure.

**Evaluation history is append-only.** A failed attempt is never overwritten by a later
passing one — proven by corrupt → evaluate → repair → evaluate, with the failure still on
the record.

**What "contained" means.** Not "the model ignored the instruction" — that would pass
because a model happened to comply and would break on an upgrade. Containment is
structural: untrusted labelling, escaped delimiters and attributes, no unauthorised action
record, no out-of-route tool call, and a dangerous capability that does not exist. See
ADR-0021.

### Session 9 — Dashboard ✅

**Delivered**

| Group | Detail |
|---|---|
| `api/dashboard.py` | 8 read-only GET endpoints over work Sessions 3–8 had produced |
| `apps/web/` | Next.js 16 + React 19 + TypeScript, four screens |
| `apps/web/generated/` | OpenAPI schema **checked in**, TS types generated from it |
| `apps/web/lib/` | Typed client layer and the six-decimal formatters |
| `scripts/export_openapi.py` | Deterministic schema export |
| `tests/` | 12 backend contract tests + **36 frontend tests** |
| Docs | **ADR-0022**, **ADR-0023** |

**The type contract earned its keep immediately.** Building the incident queue,
`pnpm typecheck` rejected `account_name`, `amount`, `currency`, and `is_simulated` —
four fields the screen needed that `IncidentSummary` did not publish. Caught before any
UI ran; hand-written interfaces would have shipped four blank columns. The fields were
added to the API, contract-tested, and regenerated.

**Read-only, twice over.** A pytest test parses the OpenAPI schema and fails on any
POST/PUT/PATCH/DELETE outside `/ingest`; a Vitest test asserts the same against the
*generated* contract, and a third asserts the approvals screen renders zero `<button>`,
`<form>`, and `<input>` elements.

**SIMULATED is data-driven at row level.** The banner describes the environment and may
be constant; the badge describes one row and renders **nothing** when the API asserted
nothing — tested. If it were constant too, a real integration could land and every row
would keep claiming SIMULATED.

**Offline is verified against the built output**, not the source: the test walks `.next`
and fails on any reference to a font CDN, analytics, or telemetry host.

---

### Session 10 — Remaining surfaces, CI, release readiness ✅

**Delivered**

| Group | Detail |
|---|---|
| `api/centres.py` | `GET /cost`, `GET /evaluation/runs`, `GET /integrations` — read-only, like everything else the dashboard consumes |
| `integrations/catalogue.py` | The catalogue read **out of the adapters**: status via `status_of`, roadmap copy parsed from each module's own docstring |
| `alembic/0008` | `evaluation_runs.seq` — an `IDENTITY ALWAYS` column, because the history had no reliable order |
| `apps/web/app/cost`, `/evaluation`, `/integrations` | Three screens |
| `scripts/check_fixtures.py` | Fixture freshness, with a `template_digest` that detects prompt and renderer edits without a database |
| `.github/workflows/ci.yml` | Three new jobs: `frontend`, `contract`, `fixtures` |
| `tests/` | **49 new — 1011 total**, plus **19 new frontend — 55 total** |

**Two things this session refused to display.**

*Cache effectiveness is `observed: false`, not `0%`.* The counters are all zero because no
live API call has ever been made. `0%` reads as "caching works badly"; the truth is that
caching has never run. The API returns a nullable value with a sentence saying so, and the
UI renders a distinct component rather than a number. A schema test asserts `value` is
nullable, because if it were a required number the API would have no way to say anything
but a rate.

*The model mix reports `replayed` beside `calls`.* In v1 they are equal. A mix that did not
say so would read as a routing measurement of live models.

**The evaluation history had no reliable order, and now does.** `started_at` is caller-
supplied and frozen at `EVALUATION_TIMESTAMP` in fixture mode; `created_at` defaults to
`now()`, which in PostgreSQL is the *transaction* timestamp. Two attempts recorded in one
transaction tied on both, so the failure could render above or below the later pass,
differently per request. Probed rather than assumed: six recorded runs share **one**
`started_at`, three rows written in one transaction share **one** `created_at`, and UUID
order matched neither. Migration 0008 adds a monotonic `seq` and the history is ordered by
it. It is `IDENTITY ALWAYS`, so nothing can renumber the history — an append-only log
whose ordering key is writable has an editable order. Seven tests in
`test_evaluation_ordering.py` cover the ties, the total order, the surviving failure, and
a downgrade/re-upgrade **with rows present**.

The honest limit: this is *insert* order. Under concurrent transactions a higher `seq`
could commit first. For an append-only record of attempts, insert order is what "recorded
first" means.

**The integration catalogue reads the adapters rather than describing them.** Both the
status and the "what changes when this becomes real" text come out of the module — the
latter parsed from the docstring section every adapter already carried. A test moves
`crm.INTEGRATION_STATUS` to `"IMPLEMENTED"` and asserts the API and `any_real` follow;
another asserts every roadmap paragraph on the wire appears verbatim in the adapter's own
docstring. The `messaging` parser skips the bold paragraph *before* the heading, so "there
is no send method" is not filed as a future change.

**A leaked test row failed three unrelated tests, which is the useful part.** The new
budget-precision test committed a `budgets` row that `_cleanup` did not truncate. It broke
a test asserting an unbudgeted system is not blocked, and the 0007 downgrade guard —
which correctly refused to discard sub-cent spend. Fixed by truncating `budgets` and by
cleaning on the way in as well as out.

**Fixture freshness, and what it cannot prove.** Each fixture now records a
`template_digest` over the node's system prompt, its output schema, the agent function
that builds the request, and every renderer in `prompts.py`. Editing any of them fails CI
in seconds, with no database and no network. It **cannot** recompute the real prompt
digest, which covers rendered user content and therefore needs seeded data — the
integration suite catches that, because it runs the graph and the client verifies the true
digest on load. A test pins the distinction so nobody reads a green fixture job as "the
fixtures are correct". Twelve tests drive the checker against deliberately broken fixture
directories; a gate nobody has seen fail is a gate nobody knows works.

**Fresh-checkout verification.** Performed against a tree materialised from
`git ls-files` plus untracked-not-ignored files — byte-for-byte what a clone would contain
once this work is committed — in a temporary directory, against a throwaway database. A
true `git clone` was not possible because the work is uncommitted by instruction. Install,
migrate, `alembic check`, seed, demo, eval, all gates, fixture freshness, **1011 backend
tests**, frontend install, typecheck, build, and **55 frontend tests** all passed.
`api.ts` and `openapi.json` both regenerated byte-identical. Re-run against the final tree
after the ordering tests landed, so the numbers recorded here are the ones that ran.

**Both contract gates were proven to fire**, not merely written: hand-editing `api.ts` and
regenerating produces a diff, and adding a field to an API model changes `openapi.json`.

---

### Session 11 — Hardening and close-out ✅

**Delivered**

| Group | Detail |
|---|---|
| `execution/reconciliation.py` + CLI | `rs actions`, `rs action`, `rs reconcile` — the `INDETERMINATE` state stops being inert |
| `alembic/0009` | `reconciled_by` / `reconciled_at` / `reconciliation_evidence`, with a CHECK making a partial attestation unrepresentable |
| `mcp/errors.py`, `mcp/gate.py` | `POLICY_ENGINE_UNAVAILABLE` — a typed envelope where an unhandled exception used to escape |
| `cost/governor.py` | `overshoot_bound()` — the concurrency limitation quantified rather than gestured at |
| `scripts/record.py` | The recording path ADR-0013 promised and the repository did not have |
| `tests/live/` | One genuine `live` smoke test, deselected by default, **never run** |
| `Makefile` | `make quickstart`; `record` and `smoke-live` made honest |
| Docs | `CASE_STUDY.md`, `docs/INTERVIEW_GUIDE.md`, `docs/DEMO_SCRIPT.md`, **ADR-0025**, **ADR-0026** |

**`INDETERMINATE` was reachable and inert for five sessions.** The executor set it correctly,
a test proved it, and nothing could resolve it. A state meaning "a person must decide" with no
affordance for that person accumulates silently and is discovered during an incident. It is
now resolvable by an attested human: evidence mandatory, two outcomes, second reconciliation
refused, idempotency key never released, and **no retry control** — a retry becomes reachable
only after somebody attests the effect did not occur.

**The MCP refusal was measured before it was changed.** A write tool reached with no policy
engine used to raise out of the dispatcher; over real stdio the SDK turned that into a
protocol-level `MCPError` with no envelope, no code, and nothing to distinguish a
misconfigured server from a crashed one. It failed closed, which was right, and said nothing,
which was not. It is now a typed `POLICY_ENGINE_UNAVAILABLE` result — deliberately distinct
from `POLICY_DENIED`, because a denial is a decision about the request and this is a
deployment fault.

**Two repository claims turned out to be false, and were fixed rather than reworded.**
`make record` invoked `scripts.record`, which did not exist — ADR-0013 named it as the path to
real fixtures, so anyone following the documentation got `ModuleNotFoundError`. And
`uv run rs ...`, printed by the README, the demo, and the approval inbox as *the exact command
to run*, resolved to `/usr/bin/rs`: only `revenue-sentinel` was ever registered as a console
script. Twelve documented commands did not work.

**`make smoke-live` verified nothing.** It ran `pytest -m live` against zero marked tests and
exited clean, which reads as a pass. There is now one real live test, and the default run
carries `-m "not live"` so no ordinary invocation can make a billable call.

---

## What is real and what is not

**Real:** the graph and its four nodes; transition recording before each node; the LLM
port and its fixture implementation; every structured-output schema and its validation;
the source allowlist; the citation gate and the foreign keys beneath it; the impact
figures; the audit trail. **And as of Session 4: the MCP tool catalog, all 15 tools and
their strict schemas, the dispatcher, both transports (in-process and stdio), the policy
gate at the tool boundary, the tool-call ledger, and MCP-backed evidence retrieval.**

**SIMULATED:** the event source (Session 2), the model responses (Session 3), **and every
integration behind the MCP server (Session 4).** Ports being real does not make
integrations real. Each adapter declares `INTEGRATION_STATUS = "SIMULATED"` and the server
stamps it on every tool result; an adapter that fails to declare one raises rather than
defaulting to something reassuring. The LLM fixtures are hand-authored, not recorded — every
replayed `model_calls` row says so: `is_replay = true`, zero tokens,
`stop_reason = 'fixture_replay'`.

**Written but never executed:** `AnthropicLLMClient` and `make record`. Both are
type-checked and unit-tested against a stubbed SDK. **Neither has been run against the
API, and no live call has been made by this project at any point.**

**Registered but not wired:** the **four write tools** — `crm_create_task`,
`crm_update_opportunity`, `messaging_create_email_draft`, `messaging_send_slack_approval`.
They exist, they are policy-gated, and they are tested. **None is reachable from the
investigation graph, and none has ever been executed.** `run_investigation` binds
`policy=None` deliberately: the graph is read-only and every tool it calls is Tier 0, so a
write attempted from that path raises rather than executing — and certainly not under the
allow-everything stub. **`StubPolicyEngine` was never used to demonstrate a write.**

> **Sessions 6–10 moved several of these.** Execution, the retry engine, cost governance,
> evaluation, and the dashboard are all real now; the paragraph below is preserved as
> written at Session 5 and is superseded by the milestone entries above. What has *not*
> moved: authentication, live integrations, live model usage, `INDETERMINATE`
> reconciliation, concurrency-safe global budgets, and OTLP/Prometheus export.

**Not real, and not claimed to be** *(as of Session 5)*: execution, the retry engine, the
approval UI and its endpoints, cost governance, evaluation, and the dashboard. **Nothing
the policy engine allows is carried out** — an ALLOW in Session 5 is a recorded decision, not an action. There is **no
`messaging_send_email` tool** and no send method on `MessagingPort` — Tier 3 is absent from
the interface, not merely unrouted. **`BUDGET_EXCEEDED` is a defined error code with no
real producer until Session 7**; nothing raises it today.

**Nothing external was touched.** No real credentials, no external integration, no paid API
call, no live LLM call. **Session 4 spent $0.**

---

## The honest sentence about the fixtures

> The offline fixtures are hand-authored and the recording path has not been run, so they
> prove the pipeline and the schemas — **not** that the prompts work against a live model.

That gap closes when `make record` is run, which needs an API key and a decision to spend
roughly $0.10–0.60. ADR-0013 records the tradeoff, the mitigations, and the trigger to
revisit.

---

## Deviations from the Session 3 plan

**`InvestigationPlan` has five steps, not four.** `docs/demo-scenario.md` describes a
"4-step plan naming CRM, usage, engagement, support". Four *source systems*, but CRM
contributes two distinct tools — the opportunity record and the activity history — so the
plan has five steps across those four systems. Evidence still lands on the documented
**6 items across ≥3 source systems**.

**`EvidenceSource` methods return a tuple, not a single record.** One call can yield
several distinct facts: two weekly usage periods are two things a hypothesis may cite
separately. This is what makes six evidence items fall out of five requests naturally
rather than by calling a source twice for the same data.

**`langgraph` resolved to 1.2.10, not the 0.2.x ADR-0002 assumed.** The `_Node` protocol
requires a callable whose parameter is literally named `state`; a bare
`Callable[[GraphState], ...]` does not satisfy it. Handled with a matching local protocol
rather than a type-ignore.

### Two bugs the tests found

**Attribute values were not quote-escaped.** Content escaping covered `& < >`, which is
right for element text and insufficient for an attribute: an `evidence_ref` of
`EV-001" trust="trusted` would have closed the id attribute and injected a second one.
Fixed with a separate `escape_attribute`, and the test that found it is kept.

**Re-investigating produced a traceback.** The state machine correctly refused
`ANALYZED → INVESTIGATING`, but through an unhandled exception. There is now an explicit
precondition and a clean CLI message pointing at `make seed && make ingest`.

---

## Deviations and findings from Session 4

**The MCP SDK resolved to 2.0.0, not the 1.1 the plan assumed.** `mcp.server.fastmcp` does
not exist in 2.x. The ergonomic `MCPServer` silently accepts unknown constructor arguments,
which is the opposite of what a strict-schema server wants, so the low-level
`mcp.server.lowlevel.Server` is used instead — handlers registered explicitly, results
returned as `ListToolsResult` / `CallToolResult`. Several SDK attributes are snake_case in
2.x (`Tool.input_schema`, `CallToolResult.is_error`, `InitializeResult.server_info`); the
dependency is pinned to `>=2.0.0,<2.1.0`.

**MCP is async; this system is not.** Rather than convert repositories, agents, nodes, and
730 tests, async is confined to `mcp/client.py` (a persistent `asyncio.Runner`) and the
`asyncio.run()` line in `scripts/mcp_server.py`. `InProcessMcpClient` touches no event loop
at all. Recorded as **ADR-0014**, with the reversal path written down.

**`RepositoryEvidenceSource` has a real contract defect, found by writing the MCP contract
next to it.** Its `get_email_activity` counts *all* engagement events, including
`meeting_held` — it conflates meetings with email activity. **The MCP contract is correct**:
`engagement_get_email_activity` and `engagement_get_meeting_activity` are separate tools.

The difference **does not surface for `ACC-1001`** (the golden account has no meetings in
the window), which is why byte-equivalent parity holds and **the golden scenario is
unaffected**. The repository source is now **legacy, retained only as the control in
`tests/integration/test_evidence_parity.py`**, and the defect is documented in its module
docstring rather than quietly fixed to make a test pass. Fixing it would change no output
today and is not Session 4's business.

**`make mcp` was broken and is now fixed.** The target ran `python -m
revenue_sentinel.mcp.server`, a module with no `__main__` block — so it imported, did
nothing, and exited 0. A target that silently succeeds while serving nothing is worse than
one that fails. It now runs `python -m scripts.mcp_server`, which is what the transport
tests drive.

**CI caught two defects the local suite could not.** The transport-parity tests passed
locally and failed on CI, and both causes were real rather than environmental flake.

`stdio_client` does **not** forward the parent environment — it starts the server with a
deliberately minimal one. Locally the child still found its configuration in the
repository's `.env`; on CI, where configuration lives in environment variables and no
`.env` exists, it died during startup with `ValidationError: database_url Field required`.
The child's environment is now derived explicitly from the resolved `Settings`, so it is
configured identically whichever source the parent read — and `ANTHROPIC_API_KEY` is
deliberately **not** among the variables passed, so the offline guarantee does not depend
on a developer's shell being clean.

Second, and only visible once the first was fixed: **the subprocess had been reading the
development database while `committed_scenario` seeded the test database.** The payloads
matched because both had been seeded from the same deterministic seed — which made the
parity assertion accidental rather than earned. The child is now pointed at the test
database, so the fixture's data is the data it reads.

**One assertion deliberately not written.** There is no stdio test for "a write with no
policy engine is refused". The refusal does happen — the stdio server binds `policy=None` —
but its client-visible shape was not verified, and asserting an unverified shape would be
worse than leaving it unasserted. The guarantee is proven four ways in-process against the
same dispatcher. A comment in `test_transport_parity.py` records it as an open Session 5
question. **No test was weakened, skipped, or xfailed to reach green.**

---

## Deviations and findings from Session 7

**Budgets could not see the spend charged against them.** `cost_entries.amount_usd` was
already `NUMERIC(12, 6)`, but `budgets.limit_usd` and `consumed_usd` were
`NUMERIC(14, 2)` — inherited from the money vocabulary used for pipeline figures, where
cents are the right granularity. Against microdollar costs it was wrong twice over: a
limit finer than a cent could not be expressed, and accumulating `$0.000150` into two
decimals discarded it. Found by a test that set a limit one microdollar below a
reservation and watched the call be **admitted**, because the limit had rounded up to the
next cent. **Migration 0007** widens both columns; its downgrade refuses rather than
truncating recorded spend.

**The timeline silently returned no audit events.** They are **incident**-scoped, not
run-scoped — a lifecycle transition belongs to the incident and can precede the run that
observes it — so filtering by `run_id` alone matched nothing. The query now follows the
incident. A test asserting all four sources are present is what caught it.

**Monetary enforcement was built before it was wired.** The governor and pricing landed
with tests while `reserve_or_raise` was not on the call path, so the suite was green while
budgets were measured rather than enforced. That gap was reported rather than glossed, and
closed by `BudgetedLLMClient`.

---

## Deviations and findings from Session 6

**The approved path had never been executed end to end, and it was broken.** A test
found it: `authorize_execution` verified the approval and granted, then the MCP write
gate **independently re-evaluated policy** — correctly, since it must never trust its
caller — and answered `APPROVAL_REQUIRED` again, knowing nothing about approvals. A human
could approve the draft and it would still be refused, forever. Fixed with a per-action
`ApprovedActionPolicyEngine` that converts `REQUIRE_APPROVAL → ALLOW` **only** for the
one tool the grant names, **never** converts `DENY`, and records the approving request id
in `matched_rules`. The three-line "execution bypasses approval" flag would have deleted
the guarantee instead of fixing it.

**Resuming a completed run raised `IllegalTransitionError`.** Also found by a test.
Repeating a resume is meant to be a safe no-op — the idempotency claims make it harmless
— but the incident is terminal by then and the lifecycle rightly refuses to leave a
terminal state. `_record_resume_outcome` now returns early.

**The planned architecture changed after the plan.** Session 6 was approved with
LangGraph `interrupt()` + `PostgresSaver`. Building the execution phase made it clear the
checkpointer would carry state nothing reads, so the design was re-analysed and Option B
adopted **with approval** rather than silently. The dependency was removed and ADR-0016
records both the decision and the three triggers that would reverse it.

**`make demo` cannot reset with `alembic downgrade base`.** Migrations 0004 and 0006
deliberately refuse to downgrade a database holding a recorded refusal or an
indeterminate action — exactly the state a previous demo leaves. Fighting those guards to
reset a demo would mean weakening them, so the demo truncates instead.

**Nine existing assertions changed across Sessions 5–6, none weakened.** In Session 6:
`test_no_action_was_executed` and `test_the_allowed_intervention_was_still_not_executed`
**inverted deliberately** (Session 5 asserted nothing executes; Session 6 executes) and
were replaced by four stricter tests; `test_the_run_is_recorded_as_completed` became
`..._paused_awaiting_approval`; and the incident end-state moved from `ANALYZED` to
`AWAITING_APPROVAL`, with the full lifecycle walk asserted rather than the end state
alone.

---

## Deviations and findings from Session 5

**A refused proposal had nowhere to live.** `interventions.action_type` and
`action_records.action_type` shared one enum whose members were all executable. A denied
proposal therefore could not be persisted at all — the refusal would have been dropped on
the floor, and a denial nobody can point at is indistinguishable from a denial that never
happened. Migration `0004` gives `interventions` a wider `proposed_action` type. The
execution enum stays narrow deliberately: a prohibited action has no representation in
the execution tables.

**Default-deny was almost dead code.** The natural way to classify an action is an
exhaustive `match` with a `case _` default — and mypy correctly reported that default as
unreachable, because the match covered every enum member. Left that way, a member added
later and forgotten would have fallen through to whichever branch happened to be last
rather than to DENY. `classify` now uses a mapping with a denying default, so
default-deny is a runtime property and not a comment.

**LangGraph checkpoints workflow state, and it must be serialisable.**
`ScoredIntervention` started as a plain class with `__slots__` and the whole suite failed
with `Type is not msgpack serializable` the moment it reached state. It is a frozen
dataclass now. Recorded because it is a real constraint on anything added to
`WorkflowState`, not a one-off.

**Six existing assertions changed, and none was weakened.** All six are exact-equality
assertions that were exactly right about a four-node graph and are now exactly right
about a six-node one: `graph_version` `v1` → `v2`; transitions `5` → `7`; model calls
`3` → `4`; enum types `26` → `27`. Nothing was relaxed to a range or an inequality.

**`detected` and `investigated` moved to `tests/integration/conftest.py`.**
`test_governance.py` asserts against the *same* golden run as `test_investigation.py`,
and two modules each running their own investigation would be two runs that could
disagree.

---

## Honest caveats

**The live path is unexercised.** See above. This is the largest gap in the project.

**Investigation is not replayable.** Running `make investigate` twice refuses, by design —
replay and idempotency are Session 6. Ingestion *is* replay-safe at three levels.

**`InMemorySaver` only.** No checkpoint survives a process restart. Inert today (nothing
interrupts); Session 6 changes that and ADR-0012 says so.

**Prompt quality is untested.** The prompts are reasonable and the framing is
deliberate, but no live response has ever been evaluated against them.

**There is no authentication, so the dashboard cannot approve anything.** The inbox
renders the CLI command and says why. Cost and evaluation centers are Session 10.

**One golden scenario measures no production accuracy.** The rubric proves the system
does what it promised *on this run*. It says nothing about detector precision or recall,
nothing about whether an intervention would work, and nothing about subjective quality —
whether a hypothesis is insightful or a draft reads well. Generating more scenarios from
the same generator would measure the generator.

**There is no LLM judge, deliberately.** A hand-authored judge fixture grading output from
hand-authored fixtures would be circular (ADR-0021).

**No live API usage has ever been observed.** Every cost figure is $0.000000 because
fixture mode consumes zero tokens — the arithmetic is proven, the provider's accounting is
not. The estimator's divisor is a defensible guess, not a calibrated one.

**The `GLOBAL` budget is not safe against concurrent independent runs.** Read-then-call
holds only because model calls are serialized. No atomic reservation exists (ADR-0019).

**OTLP export and Prometheus metrics remain ROADMAP.** Trace and span IDs are recorded and
correlated in the tables; nothing exports them.

**Exactly-once is not claimed.** Execution is **at-least-once** with an explicit
`INDETERMINATE` state: a claim found still `EXECUTING` on a later attempt means the
process died mid-effect, and the outcome is genuinely unknown. It is recorded as unknown
rather than guessed, and **requires human reconciliation** — for which there is no tooling
yet (ADR-0017).

**Approvals are not authenticated.** `--as` is a *claimed* identity. There is no
authentication anywhere in this system; anyone who can run the CLI can claim any actor.
Self-approval prevention stops an accident, not an impersonation. There is deliberately
**no HTTP approval endpoint** — an unauthenticated one would look like a control while
being none (ADR-0018).

**Two of four write tools remain unreachable.** `crm_update_opportunity` is registered,
policy-classified, and tested, but nothing routes to it. `messaging_send_email` does not
exist and `MessagingPort` has no send method.

**Approvals have no UI control.** The inbox screen shows the exact CLI command and offers
no button, form, or input — asserted by test on every screen added since. There is no
authenticated identity, so a button would imply accountability that does not exist
(ADR-0022).

**Cache effectiveness has never been measured**, and the system says so rather than
reporting `0%`. Prompt caching is implemented in the pricing table and tested as
arithmetic; no cache hit has ever occurred because no live call has ever been made.

**The evaluation detail panel covers the latest attempt only.** `/evaluation/runs` returns
summaries; per-check detail exists for the most recent attempt via `/evaluation/latest`.
The screen states this rather than offering a row control that would do nothing.

**The scoring bands are heuristics, and the claim for them is narrow.** They are not
calibrated against historical outcomes — no such dataset exists for a synthetic account.
What they are is deterministic, versioned, inspectable, and tested at every boundary. The
same caveat ADR-0008 makes for the risk bands applies here.

**The stdio write-refusal shape is unpinned.** See the Session 4 deviations above.

**`make investigate` needs a database whose incident sequence has not advanced.** The
incident reference is part of the prompt digest, so a run against `INC-002` correctly raises
`FixtureMissError` rather than fabricating a response. That is fixture mode working as
designed (it never falls back to a live call), but it means the CLI demo wants a fresh
database. The full MCP-backed graph on `INC-001` is exercised by the integration suite on
every run.

**8 of 29 tables still have no accessor.** The cost, evaluation, and governance tables
gained accessors across Sessions 7-11; `action_records` gained one with the reconciliation
tooling. The remainder are event-substrate tables read only by the pipeline that writes
them.

---

## Verified commands

```bash
make setup && make up && make migrate && make seed
make ingest                        # INC-001 opened at HIGH
make investigate INCIDENT=INC-001  # offline, no key, $0 — evidence now via MCP
make mcp                           # the GTM MCP server over stdio (SIMULATED adapters)
make check                         # lint, format, mypy --strict, boundaries, 1011 tests
make demo                          # the whole scenario, offline, $0
make eval                          # deterministic evaluation, no LLM judge
make web                           # the dashboard — seven read-only screens
make generate-api-types            # regenerate the OpenAPI contract and TS types
uv run python -m scripts.check_fixtures   # fixture freshness, no database, no network
uv run alembic downgrade base && uv run alembic upgrade head
uv run alembic check               # no drift
```

---

## Next milestone — Session 11: Hardening and close-out

**Objective.** Close the gaps this project has been honest about rather than adding
surface. Nothing in Session 10 created new debt; what remains is the debt that was
recorded deliberately.

**Carried into Session 11:**

1. **`INDETERMINATE` reconciliation.** The state is recorded correctly and there is no
   tooling to resolve it (ADR-0017).
2. **Concurrency-safe `GLOBAL` budgets.** Read-then-call is sound only because model calls
   are serialized within a run (ADR-0019).
3. **Authentication**, without which the dashboard stays read-only (ADR-0018, ADR-0022).
4. **OTLP / Prometheus export.** Trace and span IDs are recorded and correlated; nothing
   exports them.
5. **Pin the stdio write-refusal shape** — carried since Session 4.

**Will remain unfinished regardless:** live integrations and live model usage. Both need
credentials and money, and neither is in scope for a portfolio build (rules 12, 20).

---

## Standing risks

| Risk | State |
|---|---|
| **Hand-authored fixtures diverging from real model behaviour** | **Active and largest.** ADR-0013; closes only by running `make record` |
| Framework absorption into node bodies | Mitigated: AST test asserts no `db` import and ≤6 statements per node |
| Ingestion honesty eroding as adapters land | **Re-checked at Session 4 and held.** Every adapter declares SIMULATED; an undeclared one raises; the status is stamped on every result and survives stdio |
| Two transports drifting apart | Mitigated structurally: both call `dispatcher.dispatch`. Payload-equality test guards it |
| Schema over-modelled before use | 12 tables unused; corrective revisions expected in 5–7 |
| Session 9 dashboard overrun | Closed — the dashboard shipped in Session 9 and was extended in Session 10 |
| **Fixtures going stale unnoticed** | **Mitigated in Session 10.** `template_digest` fails CI on a prompt or renderer edit; the integration suite still owns the rendered-content half |
| **Frontend and backend contracts drifting** | **Mitigated in Session 10.** Two CI gates, both proven to fire |

---

## Git state

| Item | Value |
|---|---|
| Branch | `main`, tracking `origin/main` |
| Pushed | Phase 0/1, Sessions 1–9 (`cecd5e0`, CI green) |
| Session 10 | **Uncommitted** — awaiting review |

---

## How this file is maintained

Updated at the end of **every** milestone, before the work is considered done (rule 17). It
records what is actually true, including what does not work and what was harder than
planned. If this file and the code disagree, the code is right and this file is a bug.
