# ADR-0002: LangGraph orchestrates; it is not the architecture

**Status:** Accepted
**Date:** 2026-08-01
**Deciders:** Mahima Advilkar

## Context

The workflow needs explicit state, conditional routing, checkpointing, retries, and
human-in-the-loop interrupts. Two credible options: adopt LangGraph, or build a typed state
machine we own.

Building it ourselves would give total control over checkpoint semantics and make the audit
trail native rather than adapted. Adopting LangGraph gives a well-understood runtime, a
name reviewers recognize, and conditional-edge and interrupt primitives that already work.

The genuine risk with a framework is not the dependency — it is **absorption**: agent
logic, policy rules, calculations, and persistence migrate into node bodies until the
framework's programming model *is* the architecture, and the system can no longer be
tested, reasoned about, or extracted without it.

## Decision

**Use LangGraph for orchestration, and constrain it to orchestration.**

LangGraph owns: graph topology, conditional routing, execution checkpointing, retry
policy, and the human-in-the-loop interrupt.

LangGraph does **not** own: domain logic, policy rules, calculations, persistence,
adapters, or audit logging. Those live in separate typed modules and are called *from*
nodes, never implemented *inside* them.

Three rules make this concrete:

1. **Nodes are thin.** A node body reads typed fields off `WorkflowState`, calls exactly
   one service in `agents/`, `analytics/`, or `governance/`, and returns a typed
   `StateDelta`. If a node body needs a comment to explain its logic, that logic belongs in
   a service.
2. **Our tables are the source of truth.** Every transition is written to
   `workflow_transitions` before the next node runs. LangGraph's checkpointing is used for
   *execution resume only*. If the two ever disagree, our tables are correct — the
   checkpoint is a performance optimization, not a record.
3. **`agents/` does not import `db/`** (rule R5). State is passed in; deltas are returned.
   Agents are testable as pure functions with no graph and no database.

The consequence of rule 3 is worth stating plainly: **the entire agent layer can be tested
without LangGraph running at all.**

## Alternatives considered

**Custom typed state machine.** Roughly 300 lines we would own, with audit and idempotency
native rather than layered on. Rejected: it would consume Day-3 time that the vertical
slice needs, and the constraints above already prevent the framework from taking over.
Owning a runtime is only worth it if the framework's semantics actively fight you, and
LangGraph's do not.

**LangGraph with the framework as the architecture** — state in LangGraph's store, policy
inside nodes, its checkpointer as the record of truth. Rejected: this is the absorption
failure mode. The audit trail becomes a framework artifact, testing requires the runtime,
and the extraction path in ADR-0001 closes.

**A plain async function chain.** Rejected: conditional routing, resume-after-interrupt,
and retry would all be hand-rolled anyway, with none of the ecosystem benefit.

## Consequences

**Easier:** conditional edges, interrupts, and resume are provided; a recognized framework
on the résumé; less runtime code to maintain.

**Harder:** two persistence mechanisms exist (our tables and LangGraph's checkpointer) and
must be kept consistent; a LangGraph upgrade could change checkpoint semantics; the
"nodes are thin" rule needs discipline, since the framework does not enforce it.

**We now owe:** a decision on the concrete checkpointer implementation, deferred to Day 3
when the graph is real. The candidates are an in-memory saver during development with our
tables as durable truth, or a Postgres saver alongside them. In either case, reconciliation
is one-directional — our tables are authoritative.

We also owe a code-review check that node bodies stay thin. A fat node is the leading
indicator of absorption.

## Revisit when

LangGraph's checkpoint semantics conflict with our audit or idempotency requirements; a
version upgrade breaks the interrupt/resume contract; or node bodies begin accumulating
logic that resists extraction. Any of those is the signal to reconsider owning the runtime.
