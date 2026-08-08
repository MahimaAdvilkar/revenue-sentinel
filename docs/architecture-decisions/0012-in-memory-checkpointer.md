# ADR-0012: `InMemorySaver` in Session 3; a durable checkpointer when resume needs one

**Status:** Accepted
**Date:** 2026-08-04
**Deciders:** Mahima Advilkar

## Context

[ADR-0002](0002-langgraph-orchestration-boundary.md) closed with an explicit debt:

> **We now owe:** a decision on the concrete checkpointer implementation, deferred to
> Day 3 when the graph is real. The candidates are an in-memory saver during
> development with our tables as durable truth, or a Postgres saver alongside them.

Session 3 is when the graph became real, so the debt is due.

Two things about the environment turned out to differ from what ADR-0002 assumed.
`pyproject.toml` declares `langgraph>=0.2.50`; the resolved version is **1.2.10**, a
major version on from the API the ADR was written against. And `langgraph-checkpoint-postgres`
is a **separate distribution that is not installed** — only `langgraph.checkpoint.memory`
is importable today.

The workload also matters. Session 3's graph is linear, runs to completion in a single
process, and has no interrupt. Nothing in it needs a checkpoint to survive anything.

## Decision

**Use `InMemorySaver` for Session 3. Add a durable checkpointer in Session 6, when
interrupt-and-resume across a process restart genuinely requires one.**

`workflow_transitions` remains the durable record either way. That is not a
consequence of this choice — ADR-0002 rule 2 already established it, and this decision
changes nothing about it:

> If the two ever disagree, our tables are correct — the checkpoint is a performance
> optimization, not a record.

So the practical effect of an in-memory checkpointer in Session 3 is: nothing. There is
no state whose loss would matter, because the state that matters is in PostgreSQL, written
before each node runs.

## Alternatives considered

**Install `langgraph-checkpoint-postgres` now.** Rejected for Session 3, not on
principle but on timing. It adds a dependency, a table set owned by a framework
alongside our own, and a second thing to reconcile — none of which buys anything until
there is an interrupt to resume from. ADR-0001's extraction path also stays cleaner the
longer framework-owned tables stay out of the database.

**Write our own checkpointer over `workflow_transitions`.** Rejected: it re-implements a
framework primitive to avoid a dependency we will want anyway, and it puts our audit
table on the hot path of a framework's internals — the coupling ADR-0002 exists to
prevent, in the opposite direction.

**No checkpointer at all** (`compile()` without one). Rejected: LangGraph's interrupt and
resume primitives require a checkpointer, and compiling without one in Session 3 would
mean changing the compile call in Session 6 anyway. Passing `InMemorySaver` now means
Session 6 changes one argument.

## Consequences

**Easier:** no new dependency; no framework-owned tables; Session 3 stays focused on the
graph rather than on persistence semantics; the compile site is already shaped for the
swap.

**Harder:** a process restart loses the checkpoint. Today that is inert — a Session 3 run
either completes or fails and is re-run from the start. It stops being inert the moment
`await_approval` exists, which is exactly when this decision expires.

**We now owe:** Session 6 must install `langgraph-checkpoint-postgres`, pass its saver at
compile time, and prove resume across a genuine process exit — not a simulated one. The
Session 6 acceptance criteria already require that ("interrupt and resume across a process
restart"), so the obligation has a home.

## Revisit when

**Session 6 begins.** This decision is scoped to a graph with no interrupt, and Session 6
introduces the interrupt. That is the trigger, and it is on the schedule rather than
hypothetical.

Sooner, if either of two things happens: a Session 3 or 4 run becomes long enough that
losing it to a crash is expensive, or LangGraph 1.x checkpoint semantics turn out to
conflict with our transition table in a way that makes the one-directional reconciliation
in ADR-0002 rule 2 untrue.


---

## Amendment, 2026-08-08 (Session 6)

**Status: still Accepted. Not superseded.**

This ADR's "revisit when" trigger was *a human approval genuinely has to survive the
process exiting*. Session 6 introduced exactly that, so the trigger fired and the
decision was reviewed as promised.

The review did **not** produce a durable framework checkpointer. It concluded that the
requirement was already satisfied by **durable business state**: by the time the workflow
pauses for approval, everything needed to resume -- interventions, policy evaluations,
the approval request, and the action records already written -- is committed to
PostgreSQL. `langgraph-checkpoint-postgres` was installed, evaluated, and **removed**;
resume is proven by an integration test that destroys the original session and engine and
resumes against a fresh one.

So the original decision stands with its reasoning updated: `InMemorySaver` remains
correct for this graph, because this graph has no mid-*analysis* interrupt. The human
interrupt lives at the execution boundary, below the graph, where our own tables are the
substrate.

See [ADR-0016](0016-durable-business-state-resume.md), which also records the three
conditions that would make a durable checkpointer the right answer after all.
