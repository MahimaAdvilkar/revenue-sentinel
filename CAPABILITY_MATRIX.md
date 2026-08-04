# Capability Matrix

**Last updated:** 2026-08-03 — end of Session 2
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
> is connected. Real ports and adapters arrive in Session 4.
>
> **Eight detectors are registered; exactly one is implemented.** The other seven raise
> `NotImplementedError` and are ROADMAP. A test asserts the count, so "eight detectors"
> cannot be claimed anywhere, including by accident.
>
> **No agent node, no LLM call, no MCP tool, no policy engine, and no dashboard exists.**
> This system has still never called a model.

---

## 1. Layer 1 — Integration & MCP

| Capability | Status | Notes |
|---|---|---|
| GTM MCP server (custom, 15 tools) | SCAFFOLDED | Designed in [`docs/mcp-design.md`](docs/mcp-design.md); built Session 4 |
| CRM adapter | SCAFFOLDED → SIMULATED | Fixture-backed; real HubSpot/Salesforce is ROADMAP |
| Product-usage adapter | SCAFFOLDED → SIMULATED | Real warehouse/Segment is ROADMAP |
| Engagement adapter | SCAFFOLDED → SIMULATED | Real Gmail/Outlook is ROADMAP |
| Support adapter | SCAFFOLDED → SIMULATED | Real Zendesk/Intercom is ROADMAP |
| Enrichment adapter | SCAFFOLDED → SIMULATED | Real Clearbit/Apollo is ROADMAP |
| Messaging adapter (drafts, Slack) | SCAFFOLDED → SIMULATED | Real Gmail drafts/Slack is ROADMAP |
| **Sending email (as opposed to drafting)** | **NOT A CAPABILITY** | Tier 3 — deliberately not built. See [`docs/security-model.md`](docs/security-model.md) |

### The 15 MCP tools

All SCAFFOLDED as of Phase 1; all become SIMULATED on Session 4.

`crm_search_accounts` · `crm_get_account` · `crm_get_opportunity` ·
`crm_list_account_activities` · `crm_create_task` · `crm_update_opportunity` ·
`product_get_usage_summary` · `engagement_get_email_activity` ·
`engagement_get_meeting_activity` · `support_get_open_issues` ·
`enrichment_get_company_profile` · `messaging_create_email_draft` ·
`messaging_send_slack_approval` · `analytics_calculate_pipeline_impact` ·
`audit_write_event`

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
| Investigation Planner | **LLM** | SCAFFOLDED | 3 |
| Research Agent | **LLM** (tool choice) | SCAFFOLDED | 3 |
| Revenue Analyst — hypotheses | **LLM** | SCAFFOLDED | 3 |
| Revenue Analyst — impact | Deterministic | **Calculator IMPLEMENTED**, agent SCAFFOLDED | 1 (calculator), 3 (wired into the graph) |
| Strategy Agent — draft | **LLM** | SCAFFOLDED | 5 |
| Strategy Agent — ranking | Deterministic | SCAFFOLDED | 5 |
| Policy & Risk Agent | Deterministic | SCAFFOLDED | 5 |
| Execution Agent | Deterministic | SCAFFOLDED | 6 |
| Evaluation Agent | Deterministic rubric | SCAFFOLDED | 8 |
| Cost Governor | Deterministic | SCAFFOLDED | 7 |

| Capability | Status | Session |
|---|---|---|
| LangGraph state machine | SCAFFOLDED | 3 |
| Persisted state transitions | SCAFFOLDED | 3 |
| Checkpoint and resume | SCAFFOLDED | 3 |
| Human-in-the-loop interrupt | SCAFFOLDED | 6 |
| LLM judge for subjective quality | ROADMAP | — |

---

## 4. Layer 4 — Governance & Approval

| Capability | Status | Session |
|---|---|---|
| Deterministic policy engine | SCAFFOLDED | 5 |
| Four-tier risk classification | SCAFFOLDED | 5 |
| Default-deny for unclassified actions | SCAFFOLDED | 5 |
| Approval requests with expiry | SCAFFOLDED | 5 |
| Approval inbox (UI) | SCAFFOLDED | 9 |
| Delegation / role-based approval | ROADMAP | — |

---

## 5. Layer 5 — Intelligence & Memory

| Capability | Status | Session |
|---|---|---|
| Claude API client (`claude-opus-5`) | SCAFFOLDED | 3 |
| Structured outputs (schema-validated) | SCAFFOLDED | 3 |
| Fixture LLM client (offline) | SCAFFOLDED | 3 |
| Prompt caching | SCAFFOLDED | 7 |
| **Deterministic pipeline-impact calculator** | **IMPLEMENTED** | 1 — [`analytics/pipeline_impact.py`](src/revenue_sentinel/analytics/pipeline_impact.py); 60 tests, exact to the cent |
| **Deterministic intervention scoring** | SCAFFOLDED | 5 |
| Banded risk factors (ADR-0008) | **IMPLEMENTED** | 1 — [`analytics/risk_bands.py`](src/revenue_sentinel/analytics/risk_bands.py); every band boundary tested |
| Memory (Postgres tables) | SCAFFOLDED | 3 |
| Vector / semantic retrieval | ROADMAP | — |

---

## 6. Layer 6 — Cost & Observability

| Capability | Status | Session |
|---|---|---|
| Tool-call ledger | SCAFFOLDED | 4 |
| Model-call ledger | SCAFFOLDED | 7 |
| Cost ledger (`NUMERIC(12,6)`) | SCAFFOLDED | 7 |
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
| Offline fixture demo mode | SCAFFOLDED (Session 3) |
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
