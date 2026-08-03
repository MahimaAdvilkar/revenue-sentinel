# Capability Matrix

**Last updated:** 2026-08-02 — end of Session 1
**Rule:** every capability in this repository carries exactly one of four statuses, and the
status shown here matches what the code and the dashboard say (rules 5 and 19).

| Status | Meaning |
|---|---|
| **IMPLEMENTED** | Working, tested, real. Does what it claims. |
| **SIMULATED** | Working and tested, but backed by deterministic local fixtures rather than a real external system. **Never presented as real.** |
| **SCAFFOLDED** | Structure, interface, or contract exists; behaviour does not. |
| **ROADMAP** | Designed and documented; not built. |

> **As of Session 1 there are 11 IMPLEMENTED capabilities**, all of them foundational:
> configuration, logging, the clock, identifiers, domain models, the schema, migrations,
> repositories, deterministic seeding, the pipeline-impact calculator, `GET /health`, and
> boundary enforcement.
>
> **There are still zero SIMULATED capabilities**, because no adapter exists yet — the
> seeded GTM data is loaded directly into the mirror tables by
> [`db/seeding.py`](src/revenue_sentinel/db/seeding.py), not fetched through an adapter. Every
> seeded row carries `is_simulated = true` regardless.
>
> **No agent, no LLM call, no MCP tool, and no dashboard exists.** Nothing in this system
> has yet spoken to a model or to an external system of any kind.

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
| Canonical event envelope (domain model) | **IMPLEMENTED** | 1 — model and `trust_level` guarantee; ingestion in 2 |
| Event ingestion (replay-safe) | SCAFFOLDED | 2 |
| Event normalization | SCAFFOLDED | 2 |
| Detector framework | SCAFFOLDED | 2 |
| **`stalled_opportunity` detector** | SCAFFOLDED | 2 — the only detector implemented in v1 |
| Incident lifecycle state machine | SCAFFOLDED | 2 |
| Signal deduplication | SCAFFOLDED | 2 |

### Additional scenarios — contracts only

| Scenario | Status |
|---|---|
| Renewal risk | ROADMAP — registry contract, no implementation |
| Deal slippage | ROADMAP — registry contract, no implementation |
| Product-qualified account discovery | ROADMAP — registry contract, no implementation |
| Account expansion | ROADMAP — registry contract, no implementation |
| CRM data-quality incidents | ROADMAP — registry contract, no implementation |
| Enrichment-cost anomalies | ROADMAP — registry contract, no implementation |
| Campaign pipeline underperformance | ROADMAP — registry contract, no implementation |

---

## 3. Layer 3 — Agent Orchestration

| Agent | Implementation | Status | Session |
|---|---|---|---|
| Signal Agent | Deterministic | SCAFFOLDED | 2 |
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
| Incident APIs | SCAFFOLDED | 2 |
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
| Alembic migrations | **IMPLEMENTED** — one baseline, 29 tables, 26 enum types, downgrade returns to empty |
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
