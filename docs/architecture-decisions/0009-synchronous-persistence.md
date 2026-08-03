# ADR-0009: Synchronous SQLAlchemy for persistence

**Status:** Accepted
**Date:** 2026-08-02
**Deciders:** Mahima Advilkar

## Context

The stack is FastAPI, which is async-first, so async SQLAlchemy is the reflexive choice.
Session 1 had to decide before writing thirty models, because retrofitting the change later
touches every repository, the seeder, the migration environment, and every test fixture.

The actual workload is not what the reflex assumes. This system processes one incident at a
time through a LangGraph state machine. The dominant latency is model inference measured in
seconds; database queries are single-digit milliseconds against a local PostgreSQL holding
under a hundred rows. There is no concurrency pressure to relieve.

Against that, async persistence carries real cost: `greenlet` in the dependency chain,
`asyncio` fixtures throughout the test suite, an async Alembic environment, and a class of
bug — a synchronous call accidentally made inside an event loop — that surfaces as a
production stall rather than a test failure.

## Decision

**Use synchronous SQLAlchemy 2.0 throughout `db/`.** Synchronous `Session`, synchronous
engine, synchronous Alembic. FastAPI route handlers that touch the database are declared
`def` rather than `async def`, so Starlette runs them in its threadpool.

The API surface is unaffected: a synchronous handler in a threadpool and an async handler
both serve concurrent requests without blocking the event loop.

Session boundaries are explicit — `session_scope()` commits on success and rolls back on any
exception — rather than implicit in a framework dependency, so the transaction boundary is
visible at the call site.

## Alternatives considered

**Async SQLAlchemy with `asyncpg`.** Rejected for this workload. It optimises a bottleneck
that does not exist here, while adding `greenlet`, async test fixtures, an async migration
environment, and the sync-call-in-event-loop failure mode. The plan's Session 6 is already
the highest-risk session in the build; adding async semantics to interrupt-and-resume would
be compounding difficulty for no measured gain.

**Async for the API, sync for the seeder and CLI.** Rejected: two persistence idioms in one
codebase means two sets of repositories or a bridging layer, and the bridge is exactly where
the sync-in-async bugs live.

**Defer the decision and abstract over both.** Rejected as speculative generality. An
abstraction over sync and async SQLAlchemy is a large amount of machinery to avoid making a
choice that is cheap to revisit.

## Consequences

**Easier:** repositories are ordinary functions; the test suite needs no async fixtures; the
seeder and CLI are straightforward scripts; Alembic uses its default environment; stack
traces are readable; `join_transaction_mode="create_savepoint"` gives every test real commit
semantics inside a rolled-back outer transaction.

**Harder:** each database call occupies a threadpool worker for its duration. At Starlette's
default of 40 threads and single-digit-millisecond queries, that ceiling is far above
anything this system will approach — but it is a ceiling, and it is the thing to measure if
the assumption is ever challenged.

**We now owe:** route handlers that touch the database must stay `def`, not `async def`.
A handler declared `async def` would run on the event loop and block it on every query. This
is the one rule that makes the decision safe, and it is the one a future contributor is most
likely to break by habit.

## Revisit when

Concurrent workflow runs are supported (`docs/scaling-roadmap.md`) **and** measurement shows
threadpool saturation — connection checkout wait time appearing in traces, or request
latency rising with concurrency while query time stays flat. Both conditions, not either:
concurrency alone does not imply saturation, and the migration is only worth its cost
against a measured bottleneck.
