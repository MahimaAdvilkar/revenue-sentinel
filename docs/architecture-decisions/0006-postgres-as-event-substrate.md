# ADR-0006: PostgreSQL as the event substrate; no broker in v1

**Status:** Accepted
**Date:** 2026-08-01
**Deciders:** Mahima Advilkar

## Context

The system ingests events from five source systems, normalizes them, runs detectors, and
triggers workflows. The reflexive architecture is Kafka or Redis Streams plus a consumer
group, with Celery or similar for workflow execution.

At the volume this system actually handles — hundreds of events per day, single-digit
incidents, one workflow run at a time — a broker adds a container to run, a delivery
semantic to reason about, an offset store to manage, and a failure mode to debug. It buys
throughput that is not needed and durability that PostgreSQL already provides.

Rule 17 says not to install unnecessary infrastructure. This is the case it was written for.

## Decision

**PostgreSQL is the event substrate.** Events are rows; processing is driven by an
in-process dispatcher; side effects use the transactional outbox pattern.

| Concern | Mechanism |
|---|---|
| Durability | `raw_events` table, append-only |
| Replay safety | `UNIQUE (source_system, source_event_id)` |
| Ordering | `occurred_at` plus a monotonic sequence |
| Exactly-once effects | Outbox row + `UNIQUE (idempotency_key)` on `action_records` |
| Backpressure | Not implemented — known debt, recorded in the roadmap |

The **outbox pattern** is the part that matters. The executor writes the `action_records`
row and the outbox entry in one transaction; a dispatcher then performs the side effect and
records the result. If the process dies between the two, the effect is retried on restart
and the idempotency key guarantees it happens once. This is the same guarantee a broker
would provide, achieved with a table and a unique index.

The `EventDispatcher` interface is defined so that swapping the substrate later changes
`events/` only — the `EventEnvelope` and every detector stay untouched.

## Alternatives considered

**Kafka.** Rejected: correct at high volume, wrong here. A container, a schema registry
question, consumer-group semantics, and offset management — for hundreds of events a day.

**Redis Streams.** Rejected: lighter than Kafka but still a second datastore, and it
introduces a durability question Postgres has already answered.

**Celery / RQ for workflow execution.** Rejected: a broker plus a worker fleet to run one
workflow at a time. The LangGraph interrupt already gives us durable pause-and-resume
across process restarts, which is the actual requirement.

**In-memory queue with no persistence.** Rejected: a restart would lose in-flight work, and
rule 13 requires that state transitions are recorded.

## Consequences

**Easier:** one datastore; events, workflow state, and audit trail are queryable in a single
join; local development needs one container; transactional consistency between "decided to
act" and "recorded that we acted" is free.

**Harder:** throughput is bounded by single-writer Postgres; no consumer-group parallelism;
no built-in retention or compaction policy; polling rather than push adds latency.

**We now owe:** a retention policy for `raw_events`. An append-only table with no pruning is
fine at demo scale and a problem at any real one. The trigger to write it is the first time
the table exceeds a size that makes local restore slow.

We also owe the honesty of not overstating this. Postgres-as-a-queue is a legitimate choice
at this scale and a bad one at scale — the roadmap says so plainly.

## Revisit when

Any of: sustained ingestion exceeds what a single Postgres writer absorbs without lag;
more than one workflow runner needs to consume the same event stream; a source system
requires push-based streaming rather than polled batch ingestion; or event retention
requirements exceed what the operational database should hold.
