# Product Requirements

**Status:** AUTHORITATIVE
**Last updated:** 2026-08-01 (Phase 1)

---

## 1. Problem

Revenue leaks quietly. A high-value opportunity goes cold while the buying committee is
actively evaluating the product. A renewal slips because nobody noticed support volume
climbing. An expansion signal sits in product telemetry that the account team never sees.

The data needed to catch these is already present — it is just spread across CRM, product
analytics, engagement tooling, support, and enrichment, and nobody correlates it in time.
Revenue operations teams review pipeline weekly; the signal that matters arrives daily.

**Revenue Sentinel is a GTM control tower**: it watches those systems continuously, opens
an incident when a pattern indicates leakage or opportunity, investigates it with
specialized agents, quantifies the impact in dollars, recommends ranked interventions,
enforces policy, gets human approval where it matters, and executes what it is allowed to.

---

## 2. Users

| Persona | Needs | Uses |
|---|---|---|
| **Revenue Operations Manager** | See what is at risk across the pipeline, ranked by dollars; trust the numbers | Executive overview, incident queue, cost center |
| **Account Executive** | Know which of *my* deals need action today, and why | Incident detail, approval inbox |
| **RevOps / GTM Engineer** | Verify the system behaves correctly; tune detectors and policy | Evaluation center, incident timeline, integration catalog |
| **Sales Leadership** | Aggregate pipeline risk and intervention effectiveness | Executive overview |

The primary persona for v1 is the **Revenue Operations Manager**. The dashboard is designed
for that user; the AE approval inbox is the one surface designed for the AE.

---

## 3. Product principles

1. **Evidence before recommendation.** Every hypothesis cites the specific records it rests
   on. A recommendation without traceable evidence is not shown.
2. **The system proposes; a human disposes** — for anything customer-facing or material.
3. **Deterministic where it counts.** Money, scores, thresholds, and policy are code.
   Models classify, summarize, and explain.
4. **Nothing happens invisibly.** Every decision, tool call, model call, and dollar is
   recorded and viewable.
5. **Honest about what is real.** Simulated integrations are labelled as simulated
   everywhere they appear.

---

## 4. Scope: the first vertical slice

**One scenario, end to end, before anything is widened.**

> A high-value opportunity has had **no sales activity for 14 days**, while product usage
> from the account has **increased 40%**.

This pattern is the sharpest one in GTM: the buyer is engaged and the seller is absent.
It is also the one a human is most likely to miss, because nothing in the CRM changed.

### Required behaviours

| # | Requirement | Verified by |
|---|---|---|
| 1 | Detect the stalled opportunity | Detector unit test + eval `detects_stalled_opportunity` |
| 2 | Create a revenue incident | Eval `incident_created_once` |
| 3 | Produce an investigation plan | Schema validation + eval `plan_has_valid_steps` |
| 4 | Retrieve CRM, product-usage, and engagement evidence | Eval `evidence_covers_three_sources` |
| 5 | Generate ≥2 evidence-backed hypotheses | Eval `hypotheses_cite_real_evidence` |
| 6 | Calculate pipeline impact with deterministic code | Eval `impact_computed_deterministically` |
| 7 | Generate 3 ranked interventions | Eval `three_ranked_interventions` |
| 8 | Apply policy and risk checks | Eval `every_action_has_policy_decision` |
| 9 | Auto-create a safe internal CRM task | Eval `tier1_auto_executed` |
| 10 | Require human approval before external communication | Eval `no_external_action_without_approval` |
| 11 | Create an email draft after approval | Eval `draft_created_after_approval` |
| 12 | Prevent duplicate execution | Eval `replay_produces_no_duplicates` |
| 13 | Store state transitions, decisions, tool calls, model calls, costs, audit events | Eval `audit_trail_complete` |
| 14 | Display the full workflow in a professional dashboard | Manual review + screenshots |
| 15 | Evaluate whether the workflow behaved correctly | The eval suite itself |

Requirement 15 is not a formality: the evaluation suite is a first-class deliverable, and
requirements 1–13 are each phrased as an assertion it makes.

---

## 5. Functional requirements

### Detection
- Ingest events from five simulated source systems into a canonical envelope.
- Run registered detectors on a schedule or on demand.
- Deduplicate: one condition produces one incident.

### Investigation
- Produce a typed investigation plan naming the evidence to gather.
- Gather evidence exclusively through narrow MCP tools.
- Attach a stable `evidence_id`, source, and retrieval timestamp to each item.
- Produce ≥2 hypotheses, each citing evidence IDs that exist.

### Quantification
- Compute pipeline impact in deterministic Python, with every input recorded.
- Express impact in `NUMERIC` currency, never a float.
- Any figure shown must be recomputable by hand from the stored inputs.

### Recommendation
- Produce exactly 3 interventions, ranked by a tested composite score.
- Each intervention declares its `action_type`, expected value, effort, and risk.

### Governance
- Classify every intervention into a risk tier deterministically.
- Auto-execute Tier 1; require approval for Tier 2; deny Tier 3.
- Record every decision with the rules that matched.

### Execution
- Execute only what carries an ALLOW decision or an approval.
- Derive a deterministic idempotency key; enforce uniqueness in the database.
- Retry with bounded backoff; never silently drop a failed action.

### Observability
- Record every state transition, agent decision, tool call, model call, cost entry, and
  audit event with correlated trace and span IDs.

### Dashboard

**Status (Session 10): seven screens IMPLEMENTED, read-only. Dashboard scope is complete.**

| Screen | Question it answers | Status |
|---|---|---|
| Executive overview | What is at risk, in dollars, right now? | ✅ |
| Incident queue | Which incidents need attention, and in what order? | ✅ |
| Incident detail + timeline | What happened on this deal, why, and what did it cost? | ✅ |
| Approval inbox | What is waiting on a person? | ✅ **read-only** |
| Cost centre | What has this cost, against which budget, on which incident? | ✅ |
| Evaluation centre | Has it ever failed its own checks, and when? | ✅ **history, not a status** |
| Integration catalogue | What is actually connected, and what changes when it is real? | ✅ |

**Two panels deliberately show no number.** Cache effectiveness reports *never observed*
rather than `0%`: the counters are zero because no live API call has ever been made, and a
zero would be a measurement claim this system cannot support. The model mix reports the
replayed share beside the call count, so it cannot be read as live routing behaviour.

**The evaluation centre is a list, not a status.** ADR-0021 made attempts append-only so a
later pass cannot erase an earlier failure; a screen showing only the newest result would
undo that in the presentation layer. Ordering is by insertion sequence, because
`started_at` is frozen in fixture mode and ties.

**The approval inbox has no Approve button, deliberately.** There is no authentication in
this system, so a button would imply a session and an accountable actor that do not exist
(ADR-0018, ADR-0022). It renders the exact CLI command instead. Approving remains a
terminal action, which is friction chosen over a false affordance.

  cost center, evaluation center, integration catalog.

---

## 6. Non-functional requirements

| Category | Requirement |
|---|---|
| Reproducibility | Same seed → byte-identical seed data; same fixtures → identical workflow output |
| Offline | `make demo` completes with no network access and no API key |
| Runnable | A fresh clone installs, runs, and passes tests with documented commands at every milestone |
| Type safety | `mypy --strict` clean on `domain/` and `analytics/`; no `Any` at module boundaries |
| Test coverage | Every meaningful feature has tests; policy, scoring, and schema validation always |
| Cost ceiling | A single incident cannot exceed its run and incident budgets |
| Latency | Fixture-mode run completes in < 5 seconds |
| Security | No secrets in source; no external action without a policy decision |

---

## 7. Out of scope for v1

| Excluded | Status |
|---|---|
| Real HubSpot / Salesforce / Gmail / Slack connections | ROADMAP |
| Authentication, roles, multi-tenancy | ROADMAP |
| Sending email (as opposed to drafting it) | Deliberately never — Tier 3 |
| The seven additional scenarios (renewal risk, deal slippage, PQA discovery, expansion, CRM data quality, enrichment-cost anomaly, campaign underperformance) | Architecture + contracts only |
| Cloud deployment | ROADMAP |
| Learning / feedback loops from outcomes | ROADMAP |

The seven additional scenarios are represented in the detector registry, the capability
matrix, and the integration catalog — as declared contracts with no implementation. They
demonstrate that the architecture generalizes without pretending they are built.

---

## 8. Success criteria

**For the product:** the five-minute demo in [`demo-scenario.md`](demo-scenario.md) runs
end to end, offline, reproducibly, and every claim it makes is verifiable in the UI.

**For the portfolio:** a reviewer can read the repository and answer, without asking:
- Which parts use an LLM and which do not, and why
- How an unauthorized external action is prevented
- What a given incident cost and where the money went
- What is real and what is simulated

---

## Related documents

- [`demo-scenario.md`](demo-scenario.md) · [`system-architecture.md`](system-architecture.md) · [`evaluation-strategy.md`](evaluation-strategy.md) · [`../CAPABILITY_MATRIX.md`](../CAPABILITY_MATRIX.md)
