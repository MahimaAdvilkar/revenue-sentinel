# Project Status

**Last updated:** 2026-08-03
**Current milestone:** Session 2 — Events, signals, incidents ✅ **COMPLETE**
**Next milestone:** Session 3 — Investigation graph (awaiting approval)

---

## Where the project actually is

**Detection works end to end.** A fresh clone can install, migrate, seed, ingest, and
watch `INC-001` open — then run it again and watch nothing duplicate.

| Question | Answer |
|---|---|
| Can you run it? | Yes — `make setup && make up && make migrate && make seed && make ingest` |
| Can you run the tests? | Yes — 432 pass, 0 skipped, 0 xfailed |
| Is there data? | Yes — 92 seeded rows, 72 raw events, 72 normalized events |
| Does detection work? | Yes — 1 signal across 15 opportunities, `INC-001` opened at `HIGH` |
| Is it replay-safe? | Yes — a second cycle creates zero rows at all three boundaries |
| Does the API work? | Four endpoints: `/health`, `POST /ingest`, `GET /incidents`, `GET /incidents/{ref}` |
| Is ingestion real? | **No.** The source feed is SIMULATED — it replays our own seeded tables. |
| Does the demo work? | **No.** There is no investigation to demo — no agents, no LLM, no MCP. |
| Has this system ever called a model? | **No.** Not once. |

---

## Milestone log

### Phase 0 — Inspection and proposal ✅
### Phase 1 — Documentation and scaffolding ✅
20 documents + 7 ADRs, package boundaries, configuration. No application code.

### Session 1 — Foundations ✅
`core/`, `domain/` (29 models, 26 enums), `analytics/pipeline_impact.py`, `db/` (29 tables,
7 repositories), Alembic baseline, deterministic seeder, `GET /health`. 228 tests.
ADRs 0008–0010.

### Session 2 — Events, signals, incidents ✅

**Delivered**

| Group | Detail |
|---|---|
| `events/` | SIMULATED source feed, replay-safe ingestion, normalization, detector dispatch, one-call pipeline |
| `signals/` | Detector protocol, registry of 8, `stalled_opportunity`, 7 ROADMAP contracts |
| `incidents/` | Severity bands (ADR-0011), lifecycle state machine, creation service with audit trail |
| `analytics/windows.py` | The two window calculations detection and impact assessment share |
| `alembic/0002` | `incident_ref_seq` sequence, `UNIQUE (signal_id)` on incidents |
| `api/` | `POST /ingest`, `GET /incidents`, `GET /incidents/{incident_ref}` |
| `tests/` | 204 new tests — 432 total |
| Docs | ADR-0011, HTTP surface section, event-model and data-model updates |

**Acceptance — all eleven criteria met**

| # | Criterion | Result |
|---|---|---|
| 1 | Ingestion replay-safe — zero duplicate `raw_events` | ✅ second cycle inserts 0 of 72 |
| 2 | Every normalized event conforms, `trust_level="untrusted"` | ✅ 72/72 |
| 3 | Detector is pure — evaluation time injected | ✅ no session, no clock; AST test covers the tree |
| 4 | Fires on `OPP-2001` and nothing else | ✅ 1 signal across 15 opportunities |
| 5 | `dedupe_key` prevents a second incident | ✅ enforced at all three levels |
| 6 | Lifecycle persisted; illegal transitions rejected | ✅ audit row per transition; refusals leave no trace |
| 7 | Seven detectors registered as ROADMAP contracts | ✅ registry holds 8, exactly 1 implemented |
| 8 | `make ingest` → `INC-001` via `GET /incidents` | ✅ verified over HTTP |
| 9 | Migration `0002` up and down clean; no drift | ✅ `alembic check` reports nothing pending |
| 10 | Session 1 gates still green | ✅ 228 → 432, none weakened |
| 11 | Status, matrix, event-model, data-model updated | ✅ this commit |

**Demo result**

```
Ingestion cycle complete (source feed: SIMULATED)
  raw events offered     72      raw events inserted    72
  events normalized      72      opportunities seen     15
  signals created         1      signals deduplicated    0
  incidents opened        1      incidents         INC-001
```

Second run: `raw events inserted 0`, `signals created 0`, `signals deduplicated 1`,
`incidents opened 0`.

`INC-001` — *Northwind Logistics - Platform Expansion stalled at proposal*, `HIGH`,
`TRIAGED`, `stalled_opportunity/v1`, citing 8 normalized events.

---

## What is real and what is not

**Real:** the ingestion pipeline, replay safety at three independent database
boundaries, normalization to the canonical envelope, the detector and its thresholds,
severity bands, incident creation and reference allocation, the lifecycle state machine,
the audit trail, and four HTTP endpoints.

**SIMULATED:** the event source. [`events/sources.py`](src/revenue_sentinel/events/sources.py)
replays the locally seeded GTM mirror as though an adapter had delivered it. It carries
`INGESTION_STATUS = "SIMULATED"`, which is stamped on every ingestion response and asserted
by a test. **Nothing external is connected.** Ports and adapters arrive in Session 4.

**Not real, and not claimed to be:** every agent node, every LLM call, the MCP server, the
policy engine, execution, cost tracking, evaluation, and the dashboard. Seven of the eight
registered detectors raise `NotImplementedError`.

---

## Deviations from the Session 2 plan

**`events/outbox.py` was dropped** (approved before implementation). There is no outbox
table in the schema and its only consumer is the Session 6 executor, so building it now
would have been an untested module with no caller and no storage. The outbox pattern stays
documented as ROADMAP in `docs/event-model.md` §7.

**`Detector.evaluate()` returns a `SignalCandidate`, not a `Signal`.** The plan said
`Signal | None`. A `Signal` carries a surrogate UUID, so minting one inside `evaluate()`
would make two calls on identical input return different objects — and the purity guarantee
untestable. The detector now returns everything except identity, and the dispatcher assigns
the id. Same contract, one fewer thing the detector is responsible for.

**One Session 1 test was updated, not weakened.**
`test_the_application_exposes_only_the_health_route` asserted the route surface was exactly
`{"/health"}` — a correct assertion for Session 1 and a wrong one once Session 2
deliberately added three endpoints. It now pins the four-route surface. The requirement
moved; the assertion moved with it. No test was skipped, xfailed, or loosened.

### One defect found and fixed

Incident titles read *"Northwind Logistics - Northwind Logistics - Platform Expansion
stalled at proposal"*. CRM opportunity names conventionally already lead with the account
name, so prepending it duplicated it. The template now names the opportunity only; the
account is a separate field on every response.

---

## Honest caveats

**Ingestion is a simulation of ingestion.** It is replay-safe, normalized, and correct —
against a feed that reads our own database. The seam is real and the pipeline behind it is
real; what does not exist is a source system.

**Deduplication is per window-day.** A genuinely new evaluation day opens a second incident
on the same opportunity, which is correct for detection and wrong for a queue. Suppressing
"an incident is already open for this opportunity" belongs with the policy layer and is not
built.

**The import-linter contracts are less vacuous than in Session 1 but not yet complete.**
`events/`, `signals/`, and `incidents/` now have content, so R1 and R2 are exercised for
real. R4, R5, and R6 still forbid imports of packages that are empty.

**18 of 29 tables still have no accessor.** `workflow_runs`, `evidence_items`,
`hypotheses`, `interventions`, `policy_evaluations`, `action_records`, the cost tables, and
the evaluation tables are schema only.

---

## Verified commands

Every command below was run against this commit, from a dropped and recreated database.

```bash
make setup && make up && make migrate && make seed
make ingest                       # first run:  1 signal, INC-001 opened
make ingest                       # second run: 0 created, 1 deduplicated
make check                        # lint, format, mypy --strict, boundaries, 432 tests
uv run alembic downgrade base && uv run alembic upgrade head
uv run alembic check              # no drift
make api                          # then: curl localhost:8000/incidents/INC-001
```

---

## Next milestone — Session 3: Investigation graph

**Objective.** The first LLM-backed agents, running inside the LangGraph state machine,
producing evidence, hypotheses, and a deterministic impact figure.

**Session 2 leaves it well positioned:** `INC-001` exists in a known state (`TRIAGED`), the
lifecycle map already contains the `TRIAGED → INVESTIGATING → ANALYZED` edges the graph will
walk, and `analytics/pipeline_impact.py` has been tested to the cent since Session 1 — so
the graph consumes a calculator that already works rather than debugging both at once.

**Will remain unfinished:** MCP (evidence comes from repositories in Session 3), strategy,
policy, execution.

---

## Standing risks

| Risk | State |
|---|---|
| Ingestion honesty eroding as the pipeline gets more real | **Active.** `INGESTION_STATUS` is asserted by a test and stamped on every response; re-check at Session 4 when adapters land |
| Severity and risk bands read as arbitrary | Mitigated by ADR-0008 and ADR-0011: versioned, boundary-tested, claims stated narrowly |
| Schema over-modelled before use | **Active.** 18 tables unused; expect corrective revisions in Sessions 5–7 |
| Session 3 prompt iteration consuming the session | Not yet active. Mitigation: `DEMO_MODE=fixture` is the default and the impact calculator is already done |
| Session 9 (dashboard) overrun | Unchanged |

---

## Git state

| Item | Value |
|---|---|
| Branch | `main`, tracking `origin/main` |
| Remote | `origin` → `github.com/MahimaAdvilkar/revenue-sentinel` |
| Pushed | Phase 0/1 and Session 1 (12 commits) |
| Session 2 | Committed locally, **not pushed** — awaiting review |

---

## How this file is maintained

Updated at the end of **every** milestone, before the work is considered done (rule 17). It
records what is actually true, including what does not work and what was harder than
planned. If this file and the code disagree, the code is right and this file is a bug.
