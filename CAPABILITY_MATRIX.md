# Capability Matrix

**Last updated:** 2026-08-06 — end of Session 5
**Rule:** every capability in this repository carries exactly one of four statuses, and the
status shown here matches what the code and the dashboard say (rules 5 and 19).

| Status | Meaning |
|---|---|
| **IMPLEMENTED** | Working, tested, real. Does what it claims. |
| **SIMULATED** | Working and tested, but backed by deterministic local fixtures rather than a real external system. **Never presented as real.** |
| **SCAFFOLDED** | Structure, interface, or contract exists; behaviour does not. |
| **ROADMAP** | Designed and documented; not built. |

> **As of Session 2 the detection pipeline runs end to end.** Ingestion, normalization,
> the detector registry, the `stalled_opportunity` detector, incident creation, the
> lifecycle state machine, and four HTTP endpoints are IMPLEMENTED — on top of the
> Session 1 foundations.
>
> **The event source is SIMULATED.** [`events/sources.py`](src/revenue_sentinel/events/sources.py)
> replays the locally seeded GTM mirror as though an adapter had delivered it. It carries
> `INGESTION_STATUS = "SIMULATED"`, stamped on every ingestion response. No external system
> is connected. **Session 4 added real ports and adapters — and every adapter behind them is
> still SIMULATED.** Ports being real does not make integrations real.
>
> **Eight detectors are registered; exactly one is implemented.** The other seven raise
> `NotImplementedError` and are ROADMAP. A test asserts the count, so "eight detectors"
> cannot be claimed anywhere, including by accident.
>
> **The investigation graph runs offline.** **Six nodes**, four LLM call sites, and two
> deterministic ones, producing $108,000 weighted and $32,130 at risk on the golden
> scenario — plus three ranked interventions with three different policy outcomes.
>
> **No live model call has ever been made.** The LLM fixtures are **hand-authored**, not
> recorded (ADR-0013). `AnthropicLLMClient` and `make record` are written and unit-tested
> against a stub but have never been executed against the API. The fixtures prove the
> pipeline and the schemas; they do **not** prove the prompts work against a live model.
>
> **As of Session 4 the GTM MCP server is real.** All 15 tools are IMPLEMENTED with strict
> schemas. **Both transports are IMPLEMENTED** — the in-process client the graph and tests
> use, and a stdio server verified against a **real subprocess** (MCP handshake, JSON-RPC,
> `tools/list`, a successful read, typed `NOT_FOUND` and `INVALID_ARGUMENTS`, and
> `additionalProperties: false` as received over the wire). Both delegate to the same
> `dispatcher.dispatch`, so they share one set of handlers by construction.
>
> **Every integration is still SIMULATED,** and every tool result carries
> `integration_status = "SIMULATED"` — across both transports. An adapter module that fails
> to declare the constant raises rather than defaulting.
>
> **The investigation graph now gathers evidence through MCP.** `McpEvidenceSource` replaced
> `RepositoryEvidenceSource` behind the unchanged `EvidenceSource` port, and the evidence is
> **byte-equivalent**: fixture digests are unchanged and `INC-001` still produces 6 evidence
> items, 2 hypotheses, $108,000.00 weighted and $32,130.00 at risk.
>
> **The four write tools are registered but unwired from the graph.** No write has ever been
> executed. `StubPolicyEngine` exists but was **never used to demonstrate a write**;
> `run_investigation` binds **no policy engine at all**, so a write reached from the graph
> raises instead of executing.
>
> **As of Session 5 the policy engine is real.** Four tiers, **default-deny** for
> unclassified actions, escalation to the higher tier on ambiguity, and every decision
> recording its `matched_rules` and a readable reason. It is a pure function (ADR-0015):
> no I/O, no clock, no access to model-produced free text.
>
> **The strategy agent drafts; `analytics/` ranks.** The model supplies qualitative bands
> and no numbers at all. `import-linter` R3 forbids `analytics/` from importing
> `intelligence/` or `agents/`, so a model cannot influence the ranking even by accident.
>
> **Nothing executes.** An ALLOW in Session 5 is a recorded decision, not an action. The
> four write tools remain unwired from the graph, `run_investigation` still binds no
> policy engine, and `action_records` is empty — asserted by a test, not assumed.
>
> **No execution, no retries, no approval UI, no cost tracking, and no dashboard
> exists.**

---

## 1. Layer 1 — Integration & MCP

| Capability | Status | Notes |
|---|---|---|
| **MCP tool catalog (15 narrow tools)** | **IMPLEMENTED** | 4 — registry asserts the count; no `run_sql`, no `http_request` |
| **15 strict MCP tools** | **IMPLEMENTED** | 4 — `additionalProperties: false` per tool, asserted in-process **and over the wire** |
| **MCP dispatcher** | **IMPLEMENTED** | 4 — validate → policy gate (writes) → adapter → envelope → ledger, in one place |
| **In-process MCP transport** | **IMPLEMENTED** | 4 — what the graph and the test suite use; calls `dispatcher.dispatch` directly |
| **stdio MCP transport** | **IMPLEMENTED** | 4 — `make mcp`; verified against a **real subprocess**: handshake, JSON-RPC, `tools/list`, successful read, typed `NOT_FOUND` and `INVALID_ARGUMENTS`, strict schemas over the wire |
| **Simulated adapters (6 ports)** | **SIMULATED** | 4 — all declare `INTEGRATION_STATUS = "SIMULATED"`; an undeclared module raises |
| **Tool-call ledger** | **IMPLEMENTED** | 4 — a row for success, typed error, **and policy denial**; trace + span correlated |
| **Policy gate on write tools** | **IMPLEMENTED** | 4 — 4 write tools; no engine bound → raises; a denied write never reaches its adapter |
| **Write execution from the graph** | **NOT WIRED** | 4–5 — write tools registered and now genuinely policy-classified, but `run_investigation` still binds **no policy engine** and nothing acts on a decision. Session 6 |
| CRM adapter | **SIMULATED** | 4 — fixture-backed; real HubSpot/Salesforce is ROADMAP |
| Product-usage adapter | **SIMULATED** | 4 — real warehouse/Segment is ROADMAP |
| Engagement adapter | **SIMULATED** | 4 — real Gmail/Outlook is ROADMAP |
| Support adapter | **SIMULATED** | 4 — real Zendesk/Intercom is ROADMAP |
| Enrichment adapter | **SIMULATED** | 4 — real Clearbit/Apollo is ROADMAP |
| Messaging adapter (drafts, Slack) | **SIMULATED** | 4 — real Gmail drafts/Slack is ROADMAP |
| **Real vendor integrations** | **ROADMAP** | Nothing external is connected. No credentials exist |
| **Sending email (as opposed to drafting)** | **NOT A CAPABILITY** | Tier 3 — deliberately not built. `MessagingPort` has **no send method**, and no `messaging_send_email` tool exists. See [`docs/security-model.md`](docs/security-model.md) |

### The 15 MCP tools

**All 15 are IMPLEMENTED as of Session 4, backed by SIMULATED adapters.** The four write
tools are marked **W**: they are registered and policy-gated, but **not wired into the
investigation graph**, and none has ever been executed.

`crm_search_accounts` · `crm_get_account` · `crm_get_opportunity` ·
`crm_list_account_activities` · `crm_create_task` **(W)** · `crm_update_opportunity` **(W)** ·
`product_get_usage_summary` · `engagement_get_email_activity` ·
`engagement_get_meeting_activity` · `support_get_open_issues` ·
`enrichment_get_company_profile` · `messaging_create_email_draft` **(W)** ·
`messaging_send_slack_approval` **(W)** · `analytics_calculate_pipeline_impact` ·
`audit_write_event`

### Typed error codes

All seven are implemented and tested. `POLICY_DENIED` carries `retry=False,
alternative_route=False` — an agent is told not to route around a refusal, and that is a
tested property rather than prose.

| Code | Producer today |
|---|---|
| `INVALID_ARGUMENTS` · `NOT_FOUND` · `ADAPTER_ERROR` | ✅ real, exercised by tests and over stdio |
| `POLICY_DENIED` | ✅ real, from the gate |
| `APPROVAL_REQUIRED` | ✅ real as of Session 5 — raised by the gate when the engine returns `REQUIRE_APPROVAL` |
| `RATE_LIMITED` | Defined; the producer arrives with adapter throttles |
| **`BUDGET_EXCEEDED`** | **Defined, but has no real producer until Session 7.** Nothing raises it today |

---

## 2. Layer 2 — Event & Signal

| Capability | Status | Session |
|---|---|---|
| Canonical event envelope | **IMPLEMENTED** | 1–2 — model, normalizers, `trust_level` guarantee |
| Event source feed | **SIMULATED** | 2 — replays the seeded mirror; `INGESTION_STATUS = "SIMULATED"` |
| Event ingestion (replay-safe) | **IMPLEMENTED** | 2 — `UNIQUE (source_system, source_event_id)` |
| Event normalization | **IMPLEMENTED** | 2 — per-type normalizers; unknown types rejected |
| Detector framework and registry | **IMPLEMENTED** | 2 — pure detectors, injected evaluation time |
| **`stalled_opportunity` detector** | **IMPLEMENTED** | 2 — the only detector implemented in v1 |
| Incident creation and reference allocation | **IMPLEMENTED** | 2 — sequence-backed `INC-001` |
| Incident lifecycle state machine | **IMPLEMENTED** | 2 — illegal transitions rejected |
| Incident severity bands (ADR-0011) | **IMPLEMENTED** | 2 — banded weighted pipeline value |
| Signal deduplication | **IMPLEMENTED** | 2 — `UNIQUE (dedupe_key)` |
| Incident deduplication | **IMPLEMENTED** | 2 — `UNIQUE (signal_id)` |
| Lifecycle audit trail | **IMPLEMENTED** | 2 — every transition writes an `audit_events` row |

### Additional scenarios — contracts only

| Scenario | Status |
|---|---|
All seven are **registered contracts** as of Session 2: they declare a signal type,
version, window, and parameters, and their `evaluate()` raises `NotImplementedError`.
They are counted by the registry and excluded from execution by `implemented_detectors()`.

| Scenario | Status |
|---|---|
| Renewal risk | ROADMAP — contract registered, `evaluate()` raises |
| Deal slippage | ROADMAP — contract registered, `evaluate()` raises |
| Product-qualified account discovery | ROADMAP — contract registered, `evaluate()` raises |
| Account expansion | ROADMAP — contract registered, `evaluate()` raises |
| CRM data-quality incidents | ROADMAP — contract registered, `evaluate()` raises |
| Enrichment-cost anomalies | ROADMAP — contract registered, `evaluate()` raises |
| Campaign pipeline underperformance | ROADMAP — contract registered, `evaluate()` raises |

---

## 3. Layer 3 — Agent Orchestration

| Agent | Implementation | Status | Session |
|---|---|---|---|
| Signal Agent | Deterministic | **IMPLEMENTED** | 2 — runs upstream of the graph |
| Investigation Planner | **LLM** | **IMPLEMENTED** (fixture-backed) | 3 |
| Research Agent | **LLM** (source choice) | **IMPLEMENTED** (fixture-backed) | 3; gathers evidence **through MCP** as of 4 |
| Revenue Analyst — hypotheses | **LLM** | **IMPLEMENTED** (fixture-backed) | 3 |
| Revenue Analyst — impact | Deterministic | **IMPLEMENTED** | 1 (calculator), 3 (wired into the graph) |
| Strategy Agent — draft | **LLM** | **IMPLEMENTED** (fixture-backed) | 5 — drafts 3-5; supplies bands, never numbers |
| Strategy Agent — ranking | Deterministic | **IMPLEMENTED** | 5 — `analytics/`; the model cannot reach it (R3) |
| Policy & Risk Agent | Deterministic | **IMPLEMENTED** | 5 — one decision per intervention; decides nothing that then happens |
| Execution Agent | Deterministic | SCAFFOLDED | 6 |
| Evaluation Agent | Deterministic rubric | SCAFFOLDED | 8 |
| Cost Governor | Deterministic | SCAFFOLDED | 7 |

| Capability | Status | Session |
|---|---|---|
| LangGraph state machine | **IMPLEMENTED** | 3, extended 5 — **6 nodes**; graph ends at `evaluate_policy` |
| Persisted state transitions | **IMPLEMENTED** | 3 — written before the next node runs |
| Checkpoint and resume | SCAFFOLDED | `InMemorySaver` only (ADR-0012); durable saver in 6 |
| Human-in-the-loop interrupt | SCAFFOLDED | 6 |
| LLM judge for subjective quality | ROADMAP | — |

---

## 4. Layer 4 — Governance & Approval

> **Known technical debt, due in Session 6.** `approval_requests` has **no
> `requested_by` column**. The requesting actor is stored inside `decision_note` as the
> string `requested_by=<actor>`, and `approvals.requested_by()` parses it back out —
> which is what self-approval rejection depends on. It works and it is tested, but it is
> a workaround: the actor belongs in a real column with a real constraint, not in a free-text
> field that a future `decision_note` write could overwrite. Adding it is a Session 6
> migration, deliberately not smuggled into a session that promised not to execute
> anything. Recorded in [ADR-0015](docs/architecture-decisions/0015-policy-as-a-pure-function.md)
> and [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

| Capability | Status | Session |
|---|---|---|
| **Real policy engine** | **IMPLEMENTED** | 5 — pure function over a versioned rule set (ADR-0015). `StubPolicyEngine` / `DenyAllPolicyEngine` remain **for tests only** and are bound nowhere in `src/` |
| **Policy gate at the tool boundary** | **IMPLEMENTED** | 4 — a write tool with no engine bound raises; a denied write never reaches its adapter |
| Four-tier risk classification | **IMPLEMENTED** | 5 — `governance/tiers.py`; the material-field set is transcribed from `docs/security-model.md` §3 and a test compares them |
| **Default-deny for unclassified actions** | **IMPLEMENTED** | 5 — unknown action, unknown field, and *unspecified* field all deny. A mapping with a denying default, not a dead `case _` |
| **Escalation on ambiguity** | **IMPLEMENTED** | 5 — `max()` over matched rules; `RiskTier` is an `IntEnum` for exactly this |
| **Deterministic intervention ranking** | **IMPLEMENTED** | 5 — `analytics/intervention_scoring.py`; total ordering, tie-break fully determined |
| **Approval requests** | **IMPLEMENTED** | 5 — created on REQUIRE_APPROVAL, with `expires_at`; **expiry is evaluated on read**, so a lapsed request cannot authorise anything |
| **No self-approval** | **IMPLEMENTED** | 5 — the requesting actor cannot decide; enforced in `governance/`, not in a route |
| **Approval UI and endpoints** | SCAFFOLDED | 6 — approving something currently requires calling Python |
| Approval inbox (UI) | SCAFFOLDED | 9 |
| Delegation / role-based approval | ROADMAP | — |

---

## 5. Layer 5 — Intelligence & Memory

| Capability | Status | Session |
|---|---|---|
| Claude API client (`claude-opus-5`) | SCAFFOLDED | 3 — written and unit-tested against a stub, **never executed against the API** |
| Structured outputs (schema-validated) | **IMPLEMENTED** | 3 — no free-text parsing anywhere |
| Fixture LLM client (offline) | **IMPLEMENTED** | 3 — a miss raises; there is no fallback path |
| **Hand-authored LLM fixtures** | **SIMULATED** | 3 — ADR-0013. Not recorded from a model. |
| **MCP-backed evidence retrieval** | **IMPLEMENTED** | 4 — `McpEvidenceSource` is what `run_investigation` uses. The `EvidenceSource` port did not change |
| **Evidence parity (MCP vs. repository)** | **IMPLEMENTED** | 4 — **byte-equivalent**; fixture digests unchanged. `RepositoryEvidenceSource` is retained **only** as the parity-test control and is legacy |
| Evidence citation gate | **IMPLEMENTED** | 3 — application check plus foreign keys |
| Prompt caching | SCAFFOLDED | 7 |
| **Deterministic pipeline-impact calculator** | **IMPLEMENTED** | 1 — [`analytics/pipeline_impact.py`](src/revenue_sentinel/analytics/pipeline_impact.py); 60 tests, exact to the cent |
| **Deterministic intervention scoring** | **IMPLEMENTED** | 5 — banded recovery/effort, tier-derived risk, size-independent composite |
| Banded risk factors (ADR-0008) | **IMPLEMENTED** | 1 — [`analytics/risk_bands.py`](src/revenue_sentinel/analytics/risk_bands.py); every band boundary tested |
| Memory (Postgres tables) | SCAFFOLDED | 3 |
| Vector / semantic retrieval | ROADMAP | — |

---

## 6. Layer 6 — Cost & Observability

| Capability | Status | Session |
|---|---|---|
| **Tool-call ledger** | **IMPLEMENTED** | 4 — success, typed error, and policy denial all write a row; trace and span correlated |
| Model-call ledger | **Partial** | 3 writes rows (with `is_replay`); tokens, cache and cost in 7 |
| Cost ledger (`NUMERIC(12,6)`) | SCAFFOLDED | 7 |
| **Cost-governance enforcement** | SCAFFOLDED | 7 — **nothing refuses a call on cost today** |
| **`BUDGET_EXCEEDED` producer** | SCAFFOLDED | 7 — the error code exists; no code path raises it |
| **Retry engine** | SCAFFOLDED | 6 — `ADAPTER_ERROR` and `RATE_LIMITED` declare `retry=True`, but **no retry loop is implemented**; the caller fails |
| Budgets — run / incident / global | SCAFFOLDED | 7 |
| Non-monetary ceilings | SCAFFOLDED | 7 |
| Model routing per call site | SCAFFOLDED | 7 |
| OTel-shaped spans in logs and tables | SCAFFOLDED | 7 |
| **OTLP exporter to a real collector** | ROADMAP | — |
| Prometheus metrics | ROADMAP | — |
| Incident timeline API | SCAFFOLDED | 7 |

---

## 7. Layer 7 — Application & Dashboard

| Capability | Status | Session |
|---|---|---|
| `GET /health` | **IMPLEMENTED** | 1 — reports DB reachability; 503 when unreachable |
| `POST /ingest` | **IMPLEMENTED** | 2 — one cycle over the SIMULATED feed |
| `GET /incidents` | **IMPLEMENTED** | 2 — queue with status and severity filters |
| `GET /incidents/{incident_ref}` | **IMPLEMENTED** | 2 — detail with the originating signal |
| Approval APIs | SCAFFOLDED | 6 |
| Timeline API | SCAFFOLDED | 7 |
| Executive overview | SCAFFOLDED | 9 |
| Incident queue | SCAFFOLDED | 9 |
| Incident detail + timeline | SCAFFOLDED | 9 |
| Approval inbox | SCAFFOLDED | 9 |
| Cost center | SCAFFOLDED | 10 |
| Evaluation center | SCAFFOLDED | 10 |
| Integration catalog | SCAFFOLDED | 10 |
| **Frontend MCP views (tool catalog, tool-call timeline)** | SCAFFOLDED | 9–10 — the ledger rows exist; nothing renders them |
| Authentication | ROADMAP | — |
| Multi-tenancy | ROADMAP | — |

---

## 8. Layer 8 — Evaluation & Security

| Capability | Status | Session |
|---|---|---|
| Deterministic rubric harness | SCAFFOLDED | 8 |
| 15 workflow rubric checks | SCAFFOLDED | 8 |
| Prompt-injection corpus (6 cases) | SCAFFOLDED | 8 |
| Policy-bypass tests | SCAFFOLDED | 8 |
| Secret scanning | SCAFFOLDED | 8 |
| `import-linter` boundary enforcement | **IMPLEMENTED** | 1 — 6 contracts kept; asserted by the test suite as well as CI. Partly vacuous while the forbidden packages are empty; gains teeth in Sessions 2–6 |
| "Zero `Any`" AST check (ADR-0010) | **IMPLEMENTED** | 1 — scans `domain/` and `analytics/` |
| Wall-clock access check | **IMPLEMENTED** | 1 — proves only `SystemClock` reads the clock |
| Detector precision/recall at scale | ROADMAP | Meaningless on one fixture — see [`docs/evaluation-strategy.md`](docs/evaluation-strategy.md) §7 |
| Intervention effectiveness measurement | ROADMAP | Requires a real feedback loop |

---

## 9. Infrastructure

| Capability | Status |
|---|---|
| Docker Compose (PostgreSQL 16, port 55432) | **IMPLEMENTED** — container healthy, no conflict with the local 5432 |
| Alembic migrations | **IMPLEMENTED** — `0001` baseline (29 tables, 26 enum types), `0002` sequence + unique; every downgrade tested |
| Deterministic seeding | **IMPLEMENTED** — 92 rows, byte-identical per seed, idempotent |
| GitHub Actions CI | **IMPLEMENTED** (full matrix Session 10) — every local gate runs on push and PR |
| Offline fixture demo mode | **IMPLEMENTED** (Session 3) — a full run completes with `socket.socket` refusing; a fixture miss raises and persists nothing. The fixtures themselves are **SIMULATED** (hand-authored, ADR-0013) |
| Cloud deployment | ROADMAP — requires approval (rule 20) |
| Message broker | ROADMAP — see ADR-0006 |

---

## How this file stays honest

1. Updated at every milestone, before the session's work is considered done (rule 17).
2. `INTEGRATION_STATUS` constants in adapter modules are the source of truth for
   SIMULATED — this file reflects them, and the dashboard reads them directly.
3. A capability is only IMPLEMENTED when it is tested and does what it claims **against a
   real system**. Fixture-backed always means SIMULATED, no matter how well it works.
4. If this file and the code disagree, the code is right and this file is a bug.
