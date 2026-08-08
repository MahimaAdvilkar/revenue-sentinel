# ADR-0019: Pre-spend budget enforcement by conservative admission control

**Status:** Accepted
**Date:** 2026-08-08
**Deciders:** Mahima Advilkar

## Context

Session 7 had to make budgets real. `budgets` and `cost_entries` existed from the
baseline, but nothing consulted them, so a "budget" was a row nobody read.

The obvious implementation is to price a call after it returns and add it to a running
total. That is cheap, exact, and **not enforcement**: a limit noticed after it has been
exceeded has already been exceeded. It is reporting.

Enforcing before the call runs into a genuine problem: **output tokens are unknowable
until the call returns.** You cannot price a call you have not made.

## Decision

**Admit or refuse on a conservative worst-case bound, computed before the call. Charge
only actual usage afterwards.**

The order is the contract, implemented as a decorator (`cost/client.py`) so it cannot be
partially applied:

```
route_for(node)            deterministic routing picks model, effort, max_tokens
→ check_call_ceilings()    non-monetary: 12 model calls, 30 tool calls per run
→ estimate_input_tokens()  deterministic, conservative, never written as usage
→ reserve_or_raise()       BUDGET_EXCEEDED raised HERE, before the client
→ inner.complete_structured()
→ record_model_call()      actual provider usage
→ record_model_cost()      priced from actuals
→ consumed_usd
```

**The estimator is admission control, never billing truth.** It counts characters ÷ 3
(below the ~4 rule of thumb, so it over-counts), plus the transmitted JSON Schema, plus a
flat message overhead. Provider tokenization differs and is authoritative. The estimate
never touches `model_calls`, and a test snapshots usage across a gated call to prove it.

**Actual usage is authoritative.** Only what the provider returns is recorded and charged.

**Reservations are not persisted in v1.** The worst case decides admission and is then
discarded. Nothing writes it, so there is nothing to release, no reconciliation job, and
no way to double-charge — a refused-then-allowed sequence charges exactly once. This is
why `SUM(cost_entries) == budgets.consumed_usd` holds exactly.

**Conservative refusal is the intended error direction.** A worst case assuming full
output can refuse a call that would have fitted. That is a bounded, explainable
annoyance; a silent overspend is a budget that was never a budget.

Budget scopes are an **AND**, not a precedence order: `RUN`, `INCIDENT`, and `GLOBAL` must
all pass, and the refusal names which failed. A missing budget means *unbudgeted*, not a
limit of zero — budgets are opt-in.

**Fixture mode passes through the gate unchanged.** It is admission control, not metering:
a replayed call is still checked, still makes no network call, still reports zero tokens,
and still costs `$0.000000`. Computing a theoretical worst case must not make an offline
run look like it spent money.

## Concurrency — the honest limitation

**Read consumed → check → call is safe only because model calls are serialized.**
LangGraph runs nodes sequentially, one incident at a time, over a synchronous session
(ADR-0009). Within one run, two model calls cannot race.

**Two concurrent runs sharing a `GLOBAL` budget can both pass against the same remaining
balance.** Nothing prevents it today. The window is small and every deployment of this
system runs one workflow at a time, but it is a real race, and stating it is better than a
lock that has never been contended.

## Alternatives considered

**Post-hoc accounting only.** Rejected — reporting, not enforcement.

**Persisted reservations with release.** The correct answer under concurrency, and
rejected for v1: it adds a reservation table, a release path, a reconciliation job for
crashed holders, and a new class of leak. All to defend against a race that serialized
execution makes unreachable.

**`SELECT ... FOR UPDATE` on the budget row.** Cheaper than reservations and still
premature: it serialises calls that are already serialised, and does nothing for the
multi-process case without also holding the lock across the API call — which would mean
holding a row lock for the duration of a model inference.

**Estimate output tokens statistically from past calls.** Rejected: there are no past
calls (no live call has ever been made), and an estimator trained on nothing would be a
guess wearing a number.

## Consequences

**Easier.** Budgets refuse before spending. The arithmetic is exhaustively tested at $0.
Reconciliation is exact because reserved amounts never enter the database.

**Harder.** A large `max_output_tokens` reserves a large amount, so routing choices now
affect admission as well as cost. Tightening a route's ceiling loosens its reservation.

**We now owe** the concurrency caveat wherever budgets are displayed. The CLI and the demo
both print it.

## Revisit when

1. **Concurrent workers or runs share a budget** — the trigger for atomic reservation.
   Likely shape: a reservation row claimed transactionally, released on completion, and
   reconciled by a sweeper for holders that died.
2. **A live call is finally made** and estimator error can be measured against real usage.
   Until then the divisor is a defensible guess, not a calibrated one.
3. **A provider bills for something other than tokens** — cache storage, reasoning, or
   per-request fees — which the worst-case bound would not cover.
