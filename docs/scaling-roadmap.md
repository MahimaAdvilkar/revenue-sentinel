# Scaling Roadmap

**Status:** INITIAL — the extraction seams and scenario contracts are settled; sizing
figures and migration detail expand after the slice works. Expansion points marked ▸.
**Last updated:** 2026-08-01 (Phase 1)

The modular monolith is a starting point chosen for a single developer, not a ceiling.
This document records where the seams are and what changes when each is cut.

---

## 1. Extraction seams

The monolith is drawn so that four components can become independently deployed services
without redesign. Each already communicates through an interface rather than a function call.

| Component | Current | Extracted | What changes | Trigger |
|---|---|---|---|---|
| **GTM MCP server** | stdio subprocess | Networked MCP service | Transport only — handlers unchanged | Multiple consumers, or per-tenant credentials |
| **Workflow runner** | In-process LangGraph | Worker pool on a queue | Graph runtime moves; nodes unchanged | Runs exceed a single process's throughput |
| **Event ingestion** | Postgres table + outbox | Kafka / Kinesis + consumer group | `events/` substrate; envelope unchanged | Event volume exceeds single-writer Postgres |
| **Dashboard** | Next.js against one API | Same, behind a gateway | Auth and routing | Multi-tenant, or a public surface |

The interfaces that make these cuttable — `EventDispatcher`, `GraphRuntime`, the MCP tool
contract, the adapter ports — are all defined on Day 1. That is the real point of the
modular monolith: it is a decomposition that has not been paid for yet.

▸ *Expansion: sequencing, and the specific interface changes each cut requires.*

---

## 2. From simulated to real integrations

The port/adapter split is the migration path. Each simulated adapter's docstring already
carries a "What changes when this becomes real" section (see
[`mcp-design.md`](mcp-design.md)).

| Integration | Real target | Adds | Effort |
|---|---|---|---|
| CRM | HubSpot or Salesforce | OAuth, rate limits, pagination, field mapping, sandbox | Large |
| Product usage | Warehouse (Snowflake/BigQuery) or Segment | Query layer, freshness handling | Medium |
| Engagement | Gmail / Outlook API | OAuth, scopes, privacy review | Large |
| Support | Zendesk / Intercom | Auth, webhook ingestion | Medium |
| Enrichment | Clearbit / Apollo | API key, **per-call cost** (feeds the enrichment-cost-anomaly scenario) | Small |
| Messaging | Gmail drafts, Slack | OAuth, workspace install, send-vs-draft distinction | Large |

**No real connection is made without explicit approval** (rules 16 and 20), and no
employer or customer data is used at any point. When an adapter becomes real, its
`INTEGRATION_STATUS` constant changes from `SIMULATED` to `IMPLEMENTED` and the capability
matrix and dashboard badge follow automatically.

---

## 3. Additional scenarios

Each is a new detector plus policy rules. **The graph does not change** — that is the
architectural claim these scenarios exist to test.

| Scenario | Detector signal | Primary evidence | New policy consideration |
|---|---|---|---|
| **Renewal risk** | Support volume ↑ + usage ↓ + renewal < 90 days | Support, usage, CRM | Escalation to CSM; higher approval bar near renewal |
| **Deal slippage** | Close date pushed ≥2× in one quarter | CRM stage history | Forecast-affecting CRM writes are always material |
| **PQA discovery** | Free/trial usage crosses a qualification threshold | Product, enrichment | Outbound to a non-customer — stricter contact rules |
| **Account expansion** | Seat utilization > 90% sustained | Product, CRM | Upsell messaging requires AE approval |
| **CRM data quality** | Required fields missing on high-value opps | CRM | Bulk field writes — hard-denied without operator enablement |
| **Enrichment-cost anomaly** | Enrichment spend ↑ vs baseline | Cost ledger, enrichment | Acts on our own spend, not the customer — Tier 1 |
| **Campaign underperformance** | Pipeline created vs campaign spend below threshold | Campaign, CRM | Reporting only; no customer contact |

Each already exists as a registry contract with declared parameters and no implementation
(see [`event-model.md`](event-model.md)). They are labelled ROADMAP everywhere they appear.

▸ *Expansion: per-scenario detector parameters and evidence requirements, added as each is
implemented.*

---

## 4. Platform hardening

| Capability | v1 | Next |
|---|---|---|
| Auth | None | OIDC, roles (viewer / approver / admin) |
| Multi-tenancy | Single tenant | Tenant column + row-level security + per-tenant budgets |
| Tracing | OTel-shaped spans in logs and tables | Real OTLP exporter → collector → backend |
| Metrics | Derived from tables | Prometheus counters and histograms |
| Secrets | Env vars | Secrets manager with rotation |
| Deployment | Local compose | Container platform, migrations as a job, blue/green |
| Memory | Postgres tables | pgvector for semantic evidence retrieval |
| Model routing | Static per call site | Adaptive routing from measured eval quality |
| Evaluation | Deterministic rubric | + LLM judge for subjective quality, advisory only |

Tracing is the cheapest of these to complete: the span shape is already correct, so it is
an exporter and a collector, not an instrumentation project.

---

## 5. Scale considerations

▸ *Expansion: these are the questions to answer with measurements, not estimates. Recorded
now so they are not discovered late.*

| Dimension | v1 assumption | Question to answer before scaling |
|---|---|---|
| Events/day | Hundreds | At what volume does Postgres-as-substrate stop being honest? |
| Concurrent runs | 1 | How many workers before Postgres connections bind? |
| Incidents/day | Single digits | Does the approval inbox stay usable at 100/day? |
| Evidence per run | ~6 items | When does retrieval need vectors rather than a `WHERE`? |
| Cost/incident | < $0.15 live | What does the per-incident budget become at 1,000/day? |

The approval-inbox question is the one most likely to bite. A human-in-the-loop system
that generates more approvals than a human can process has failed, regardless of how well
the workflow runs.

---

## 6. Known architectural debt

Recorded now rather than discovered later.

| Debt | Impact | Resolution |
|---|---|---|
| `calculate_impact` runs sequentially after hypotheses | Slightly longer runs | Parallelise; only worth it once latency matters |
| Detector registry is code, not config | Tuning needs a deploy | Move thresholds to a config table |
| No backpressure on ingestion | A large batch could saturate a run | Add a queue when the broker lands |
| Single graph version | No A/B of graph shapes | `workflow_runs.graph_version` exists; the runner needs to honour it |
| Fixture-mode LLM cache keyed by prompt digest | Prompt edits silently miss the cache | Fail loudly on a fixture miss in CI |

The last one is a real trap: a silent cache miss in fixture mode would turn an offline
test into a network call. The mitigation is to make a miss an error, not a fallback.

---

## Related documents

- [`system-architecture.md`](system-architecture.md) · [`mcp-design.md`](mcp-design.md) · [`event-model.md`](event-model.md) · [`../CAPABILITY_MATRIX.md`](../CAPABILITY_MATRIX.md)
- ADR [`0001`](architecture-decisions/0001-modular-monolith.md), [`0004`](architecture-decisions/0004-simulated-integrations.md)
