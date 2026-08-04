# Event Model

**Status:** AUTHORITATIVE
**Last updated:** 2026-08-03 (Session 2)

Events are the input to the system; incidents are the unit of work. This document defines
the canonical envelope, the detector contract, and the incident lifecycle.

**Implementation status: this pipeline runs.** Ingestion, normalization, the detector
registry, the `stalled_opportunity` detector, and incident creation are implemented and
tested as of Session 2.

> **The source feed is SIMULATED.** `events/sources.py` replays the locally seeded GTM
> mirror as though a source adapter had delivered it. It does not connect to any external
> system, and it carries `INGESTION_STATUS = "SIMULATED"`, which is stamped on every
> ingestion response. Real adapters are Session 4 and later (ADR-0004).

---

## 1. Transport decision

There is **no message broker in v1**. Events are rows in PostgreSQL and processing is
driven by an in-process dispatcher plus an outbox table. This is a deliberate choice
recorded in ADR-0006: at demo scale a broker adds operational surface without adding
capability, and rule 17 says don't install unnecessary infrastructure.

The `EventEnvelope` and the dispatcher interface are shaped so that swapping the substrate
for Kafka or SQS later changes `events/` only.

---

## 2. Pipeline

```mermaid
graph LR
    SRC["Source adapters<br/>SIMULATED"] --> RAW[("raw_events<br/>append-only")]
    RAW --> NORM["Normalizer"]
    NORM --> NE[("normalized_events")]
    NE --> DISP["Detector dispatcher"]
    DISP --> D1["stalled_opportunity<br/>IMPLEMENTED (Day 2)"]
    DISP -.-> D2["renewal_risk<br/>ROADMAP"]
    DISP -.-> D3["deal_slippage<br/>ROADMAP"]
    DISP -.-> D4["pqa_discovery<br/>ROADMAP"]
    D1 --> SIG[("signals<br/>dedupe_key UNIQUE")]
    SIG --> INC[("incidents")]
    INC --> WF["Workflow run<br/>orchestration/"]

    style D2 stroke-dasharray: 5 5
    style D3 stroke-dasharray: 5 5
    style D4 stroke-dasharray: 5 5
```

Ingestion is **replay-safe**: `raw_events` is uniquely keyed on
`(source_system, source_event_id)`, so re-running ingestion produces no duplicates.

---

## 3. Canonical event envelope

Every normalized event conforms to this Pydantic model regardless of source.

| Field | Type | Notes |
|---|---|---|
| `event_id` | `UUID` | Assigned at normalization |
| `schema_version` | `str` | `"1.0"` — bumped on breaking envelope change |
| `event_type` | `EventType` | Enum, see below |
| `source_system` | `SourceSystem` | `crm` / `product` / `engagement` / `support` / `enrichment` |
| `occurred_at` | `datetime` | UTC, from the source |
| `received_at` | `datetime` | UTC, ours |
| `account_ref` | `str \| None` | Business key, e.g. `ACC-1001` |
| `opportunity_ref` | `str \| None` | Business key, e.g. `OPP-2001` |
| `attributes` | `dict[str, JSONValue]` | Typed per `event_type` at the detector boundary |
| `trust_level` | `Literal["untrusted"]` | **Always untrusted.** Source content is adversarial by assumption (rule 14). |

`trust_level` is a constant, not a variable. There is no code path that marks ingested
GTM content as trusted.

### Event types in v1

| `event_type` | Source | Used by |
|---|---|---|
| `crm.opportunity.updated` | crm | stalled_opportunity |
| `crm.activity.logged` | crm | stalled_opportunity |
| `product.usage.rollup` | product | stalled_opportunity |
| `engagement.email.activity` | engagement | evidence only |
| `engagement.meeting.held` | engagement | evidence only |
| `support.issue.opened` | support | evidence only |

Declared but not emitted in v1 (contracts for future scenarios):
`crm.opportunity.stage_changed`, `crm.record.quality_flagged`,
`enrichment.provider.usage_reported`, `campaign.performance.rollup`.

---

## 4. Detector contract

```
Detector:
    signal_type: str
    version: str
    window: timedelta
    def evaluate(context: DetectionContext) -> Signal | None
```

Detectors are **pure and deterministic** — same inputs, same output, always. They take a
`DetectionContext` (a read-only bundle of the relevant normalized events and mirrored
source rows) and return a `Signal` or nothing. No I/O, no LLM, no clock access except the
`evaluated_at` passed in.

That last point matters: passing the evaluation time in rather than calling `now()` is
what makes the detector unit-testable and the demo reproducible.

### `stalled_opportunity` — the only detector implemented in v1

| Parameter | Value | Rationale |
|---|---|---|
| `min_amount` | 100,000 USD | "High-value" threshold |
| `inactivity_days` | 14 | Days since the most recent sales activity |
| `usage_growth_pct` | 40% | Week-over-week growth in `feature_events` |
| `open_stages` | `Discovery`, `Proposal`, `Negotiation` | Excludes closed opportunities |

Fires when **all** conditions hold. The conjunction is the point: rising usage plus sales
silence is a far stronger signal than either alone, and it is exactly the pattern a human
rep misses.

`dedupe_key = sha256(signal_type | opportunity_ref | detector_version | window_start)`

`window_start` is **truncated to the UTC date**. Without truncation, two runs seconds
apart produce different keys and therefore duplicate signals -- the replay-safety
guarantee would hold under the frozen demo clock and fail silently under a real one.

Three conditions that deliberately do **not** fire, each because absent or unusable data
is not evidence of a stall:

| Situation | Behaviour |
|---|---|
| No sales activity ever logged | No signal. "Never contacted" is indistinguishable from "history not loaded". |
| Fewer than two usage snapshots | No signal. One week is not a trend. |
| Zero usage baseline | No signal. Growth from zero is undefined, and a first week of usage is not a stall. |

A non-USD opportunity also does not fire: v1 holds no exchange rates, and converting at
an unstated rate would fabricate a number.

### Registered-but-unimplemented detectors

These exist as registry entries with declared parameters and no implementation. They
appear in the capability matrix as ROADMAP and in the dashboard's integration catalog as
"contract defined".

`renewal_risk` · `deal_slippage` · `pqa_discovery` · `account_expansion` ·
`crm_data_quality` · `enrichment_cost_anomaly` · `campaign_underperformance`

---

## 5. Incident lifecycle

```mermaid
stateDiagram-v2
    [*] --> DETECTED: signal fires

    DETECTED --> TRIAGED: incident created, severity assigned
    TRIAGED --> INVESTIGATING: workflow run starts
    INVESTIGATING --> ANALYZED: hypotheses + impact complete
    ANALYZED --> STRATEGIZED: ranked interventions produced
    STRATEGIZED --> AWAITING_APPROVAL: gated action proposed
    STRATEGIZED --> EXECUTING: all actions auto-approved
    AWAITING_APPROVAL --> EXECUTING: human approves
    AWAITING_APPROVAL --> CLOSED_REJECTED: human rejects
    AWAITING_APPROVAL --> EXPIRED: approval window elapses
    EXECUTING --> COMPLETED: actions executed and evaluated

    DETECTED --> DISMISSED: false positive
    TRIAGED --> DISMISSED: false positive
    INVESTIGATING --> FAILED: unrecoverable error
    ANALYZED --> FAILED: unrecoverable error

    COMPLETED --> [*]
    CLOSED_REJECTED --> [*]
    DISMISSED --> [*]
    EXPIRED --> [*]
    FAILED --> [*]
```

| State | Meaning | Terminal |
|---|---|---|
| `DETECTED` | Signal fired, incident opened, not yet triaged | No |
| `TRIAGED` | Severity and ownership assigned | No |
| `INVESTIGATING` | Workflow running: plan, evidence, hypotheses | No |
| `ANALYZED` | Hypotheses and deterministic impact complete | No |
| `STRATEGIZED` | Ranked interventions produced, policy evaluated | No |
| `AWAITING_APPROVAL` | Blocked on a human decision (graph interrupted) | No |
| `EXECUTING` | Authorized actions being performed | No |
| `COMPLETED` | Actions executed, outcome evaluated | **Yes** |
| `CLOSED_REJECTED` | Human rejected the proposed action | **Yes** |
| `EXPIRED` | Approval window elapsed with no decision | **Yes** |
| `DISMISSED` | Judged a false positive | **Yes** |
| `FAILED` | Unrecoverable error; state preserved for inspection | **Yes** |

### Severity assignment

Severity is a banded function of weighted pipeline value, assigned at detection time and
inherited by the incident. See ADR-0011.

| Weighted value (`amount × probability`) | Severity |
|---|---|
| ≥ $250,000 | `CRITICAL` |
| ≥ $100,000 | `HIGH` |
| ≥ $25,000 | `MEDIUM` |
| < $25,000 | `LOW` |

The golden scenario computes `180,000.00 × 0.60 = 108,000.00` → `HIGH`. The bands are
deterministic, versioned (`severity_bands/v1`), and boundary-tested; they are **not**
empirically calibrated.

### How an incident is opened

An incident is created at `DETECTED` and immediately transitioned to `TRIAGED` through the
state machine, rather than being written straight to `TRIAGED`. That costs one extra audit
row and buys two things: the documented lifecycle is actually followed on the happy path,
and the triage step is recorded rather than implied.

`incidents.status` holds only the *current* state, so **every transition writes an
`audit_events` row** — without it, an incident's history would not exist anywhere. Illegal
transitions raise before anything is written, so a refusal leaves no trace: nothing
happened.

Incident references come from a PostgreSQL sequence rather than `count(*) + 1`, which is a
race under any concurrency and would pass every single-threaded test.

**Every workflow transition is persisted** to `workflow_transitions` before the next node
runs, with the originating node, the edge predicate that fired, and a state digest. Rule 13
is satisfied by construction: there is no way to move the workflow without leaving a
record. (`workflow_transitions` is written from Session 3, when a graph exists to
transition.)

---

## 6. Idempotency boundaries

Four independent layers, each at a different granularity:

| Layer | Mechanism | Prevents |
|---|---|---|
| Ingestion | `UNIQUE (source_system, source_event_id)` on `raw_events` | Duplicate raw events |
| Detection | `UNIQUE (dedupe_key)` on `signals` | A second signal for the same condition |
| Incident | `UNIQUE (signal_id)` on `incidents` | A second incident for the same signal |
| Workflow | Checkpoint + `UNIQUE (run_id, sequence)` on transitions | Re-executing a completed node on resume |
| Action | `UNIQUE (idempotency_key)` on `action_records` | The same CRM task or email draft twice |

`idempotency_key = sha256(run_id | intervention_ref | action_type | target_ref)`

The key deliberately includes `run_id`: re-running the *same* incident's workflow must not
duplicate actions, while a genuinely new incident on the same opportunity is free to act.

---

## 7. Outbox pattern

Side effects are not performed inline with the transaction that decides them. The
executor writes an `action_records` row and an outbox entry in one transaction, then a
dispatcher performs the effect and records the result. If the process dies between the two,
the effect is retried on restart and the `idempotency_key` guarantees it happens once.

Retries use bounded exponential backoff with a maximum attempt count recorded in
`action_records.attempt_count`. Exhausted retries mark the action `FAILED` and emit an
audit event — they never silently drop.

---

## Related documents

- [`data-model.md`](data-model.md) · [`agent-architecture.md`](agent-architecture.md) · [`security-model.md`](security-model.md) · [`demo-scenario.md`](demo-scenario.md)
- ADR [`0006`](architecture-decisions/0006-postgres-as-event-substrate.md)
