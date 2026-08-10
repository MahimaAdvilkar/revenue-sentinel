# ADR-0026: Concurrent `GLOBAL` budget enforcement stays a bounded, documented v1 limitation

**Status:** Accepted
**Date:** 2026-08-09
**Deciders:** Mahima Advilkar

## Context

ADR-0019 established pre-spend admission control: before a model call, the worst-case cost
is computed and every applicable budget is asked whether it can absorb it. `BUDGET_EXCEEDED`
is raised *before* the client is reached, which a test proves with a counting fake that
records zero calls.

It also recorded a limitation: enforcement is not atomic across concurrent independent
runs. The final milestone is the moment to either close that or state its boundary
precisely, because "it can race" is a shrug, not an engineering position.

Reading the code closely narrows the problem considerably:

* **Consumption is already race-free.** `cost/ledger.py` charges with
  `UPDATE budgets SET consumed_usd = consumed_usd + :amount`. Concurrent charges cannot
  lose an update; `SUM(cost_entries) == budgets.consumed_usd` holds regardless of
  interleaving.
* **Only admission races.** `CostGovernor.check_affordable()` reads `consumed_usd` and the
  caller proceeds on a value another transaction may have already moved.

So the exposure is not unbounded drift. It is a bounded overshoot: with `N` runs
concurrently admitting against the same `GLOBAL` budget, each may be admitted against a
`consumed_usd` that omits at most `N-1` other in-flight reservations, so spend can exceed
the limit by at most `(N - 1) x worst_case_reservation` before the next admission check
refuses.

Within a single run this cannot happen at all, because model calls are serialized.

## Decision

**Do not implement atomic reservations in v1. Quantify the exposure, test the bound, and
surface it.**

`CostGovernor.overshoot_bound(concurrent_runs)` returns
`(concurrent_runs - 1) * worst_case_reservation` as a `Decimal`, with unit tests pinning
its shape -- including that one run has an overshoot of exactly zero, which is the
guarantee the serialization inside a run actually provides. The cost centre and
`CONCURRENCY_NOTE` state the bound rather than gesturing at a race.

### Why not `SELECT ... FOR UPDATE`

It works, and it holds a PostgreSQL row lock across a model call. Every concurrent run
would serialize behind one budget row for the duration of a network request to a model
provider, and a single hung call would block every other run in the deployment. That is a
worse operational property than the bug it fixes. A system whose central argument is that
side-effecting work must be bounded and observable should not introduce a lock held across
an unbounded external call at its final milestone.

### Why not a reservation ledger

A `budget_reservations` table with reserve/settle/release is the textbook answer and it is
correct. It is also a new table, a migration, three new code paths, and one new failure
mode: a process that dies between reserving and settling leaks a reservation that silently
shrinks the budget until something reaps it.

That failure is `INDETERMINATE` in a second costume -- a claim whose outcome is unknown
because a process died mid-flight. This project already has one such mechanism and ADR-0025
has just built the human tooling it needs. Introducing a second instance of the same hazard,
with its own reaper and its own operational burden, to protect a $25/month budget on a
single-process demo that has spent $0.000000, is not proportionate.

### What makes this acceptable rather than lazy

The limitation is bounded, the bound is computed by code and asserted by tests, and it is
stated on the screen where the budget is displayed. A reviewer can read the exact worst
case rather than being told it is fine. That is a different thing from an undocumented race.

## Alternatives considered

**`SELECT ... FOR UPDATE` on the budget row.** Rejected -- lock held across a model call;
see above.

**Reservation ledger with settle/release.** Rejected for v1 -- recreates the
claimed-but-unresolved failure mode in a second place, for a budget whose real-world
exposure is currently zero dollars.

**Postgres advisory locks.** Same lock-across-network-call objection as `FOR UPDATE`, with
the added property that the lock is invisible in the schema, so a future reader would not
find it while reading the budget model.

**Optimistic concurrency (version column, retry on conflict).** Rejected as
underpowered here: it makes the *charge* safe, and the charge is already safe. It does
nothing about admission, which is the actual gap.

**Moving admission into the same statement as consumption** (`UPDATE ... WHERE consumed +
:amount <= limit`, admit on rowcount). Genuinely attractive and the most likely future fix,
because it is atomic with no lock held across the call. Rejected for v1 only because it
inverts the current ordering -- it consumes the worst case up front and then must refund
the difference, which reintroduces the release path a reservation ledger needs and would
break the invariant that `budgets.consumed_usd` equals the sum of real `cost_entries`
(ADR-0019/0020). Worth doing properly with its own migration and tests, not as a last-week
change.

## Consequences

**Easier.** No new table, no reaper, no lock contention, and the invariant
`SUM(cost_entries) == consumed_usd` stays exactly true.

**Harder.** A deployment that runs investigations concurrently can overshoot a hard
`GLOBAL` budget by the stated bound. Anyone doing that must read this record first, which
is why the bound appears in the API response and on the cost centre rather than only here.

**We now owe** honesty about it in every place the budget is described -- the README, the
capability matrix, and the dashboard -- and a refusal to describe `GLOBAL` enforcement as
"safe" without the qualifier.

## Revisit when

1. **The first deployment runs investigations concurrently.** This is the trigger. Not
   "when we have time" -- the moment concurrency is real, the single-statement admission
   variant above should be implemented with its refund path and tested under real
   contention.
2. **A budget limit becomes small enough that the bound is a material fraction of it.** At
   $25/month against sub-cent calls the overshoot is noise; at a $1 limit it is not.
3. **Budgets gain a scope that is shared across processes by design** (per-tenant, per-
   customer), where the racing parties are no longer a developer's parallel test runs but
   independent tenants who would each experience the other's overshoot.
