# ADR-0016: Durable business-state resume, not framework checkpoint persistence

**Status:** Accepted
**Date:** 2026-08-08
**Deciders:** Mahima Advilkar

## Context

Session 6 introduced a human approval boundary: a Tier 2 action pauses until a person
decides, and the decision may arrive minutes or days later, after the process that
paused has exited. Something has to survive that gap.

The reflexive answer -- and the one this session's own plan proposed -- is
`langgraph-checkpoint-postgres`: swap `InMemorySaver` for `PostgresSaver`, use
LangGraph's `interrupt()`, and let the framework carry graph state across the restart.
It was installed and half-wired before the question got asked properly.

The question that changed the answer: **what is actually left to resume?**

By the time the workflow pauses, the analytical work is finished and committed.
Interventions are ranked and persisted, policy decisions recorded with their matched
rules, the approval request written with its expiry, and the Tier 1 action already
executed with an `action_records` row. The only outstanding work is "execute the actions
that have become authorised", which is a pure function of rows in PostgreSQL.

## Decision

**The execution phase resumes from durable business state. LangGraph's checkpointer is
not used for approval resume, and `langgraph-checkpoint-postgres` is not a dependency.**

- `resume_investigation` reads `workflow_runs`, `interventions`, `policy_evaluations`,
  `approval_requests`, and `action_records`, and re-runs the execution phase. Nothing
  in memory is required, and no investigation node runs again.
- `InMemorySaver` remains for the analytical graph, where no human interrupt occurs.
- Duplicate prevention is **idempotency** (ADR-0017), not framework replay semantics.
- No checkpoint tables are created, and there is no second schema owner in the database.

### Graph orchestration state vs. business state

The distinction the original plan blurred:

| | Graph orchestration state | Business / execution state |
|---|---|---|
| Holds | Which node is next, channel values, pending writes | What was decided, what was authorised, what was performed |
| Owner | LangGraph | Us |
| Format | msgpack blobs | Queryable typed rows |
| Audience | The framework | Auditors, the dashboard, a revenue leader |
| Lost if dropped | The ability to resume mid-graph | The ability to know what happened |

At the approval boundary the second is a **superset** of what resume needs. The first
adds nothing a caller reads.

### Why resume starts at execution rather than replaying analysis

Replaying analysis would re-run four model call sites to reproduce evidence and
hypotheses that are already persisted and already cited by the interventions the human
approved. It would be slower, would cost money outside fixture mode, and -- worst --
could produce *different* hypotheses than the ones the approval was granted against.
An approval is consent to a specific action derived from specific reasoning; regenerating
that reasoning after the fact quietly invalidates what was consented to.

### Idempotency is the correctness mechanism

Resume is safe to call any number of times because every effect claims its
`idempotency_key` row before acting. A framework checkpointer would not have made this
unnecessary -- exactly-once delivery is not something a checkpointer provides across a
process boundary either. Idempotency has to exist regardless, and once it does, the
checkpointer's duplicate-prevention story is redundant.

## Alternatives considered

**`PostgresSaver` + `interrupt()` (the original plan).** Rejected for Session 6. It adds
two dependencies, four framework-owned tables, and a second schema owner that Alembic
autogenerate would try to drop -- requiring an `include_object` filter whose only purpose
is to protect tables nothing reads. In exchange it carries state that is already fully
materialised in business tables. Genuinely the right answer for a mid-*analysis*
interrupt; this is not one.

**Both.** Rejected explicitly. Two resume substrates means two answers to "where does
truth live", and the one that gets debugged at 2am is whichever the reader guesses.

**A bespoke serialised blob of our own.** Rejected: that is a checkpointer, written worse.

## Consequences

**Easier.** No new infrastructure. Resume is a plain function over rows, testable by
opening a new engine against the same database. The pause state is queryable -- "what is
waiting, since when, on whom" is SQL, not a blob decode. LangGraph stays what ADR-0002
says it is: topology, and nothing else.

**Harder.** Resume is *our* code, so its correctness is our responsibility rather than a
framework's. A future mid-analysis interrupt would need this decision reopened rather
than extended.

**We now owe** the guarantee that anything a resume needs is written to business tables
*before* the pause. That is enforced by the restart test, which destroys the original
session and engine and resumes against a fresh one.

## Relationship to ADR-0012

ADR-0012 (`InMemorySaver` in Session 3) is **amended, not superseded**. Its "revisit
when" trigger was *"a human approval genuinely has to survive the process exiting"* --
which happened in Session 6. The trigger fired, and the review it demanded concluded that
a durable **framework checkpoint** was the wrong remedy: the requirement was satisfied by
durable **business state** instead. `InMemorySaver` remains correct for a graph with no
mid-graph interrupt, so the decision stands with its reasoning updated rather than
replaced.

## Revisit when

Any one of these, at which point a durable checkpointer likely becomes correct:

1. **A true mid-analysis interrupt** -- the workflow must pause *between* analytical
   nodes, where partial reasoning is not yet materialised in business tables.
2. **Long-running graph state not fully materialised** -- a node accumulates state that
   is expensive to recompute and has no natural home in the domain schema.
3. **Parallel branches whose continuation cannot be reconstructed** from persisted domain
   state -- fan-out where "which branches finished" is a framework fact rather than a
   business one.
