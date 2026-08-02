# ADR-0001: Modular monolith with enforced layer boundaries

**Status:** Accepted
**Date:** 2026-08-01
**Deciders:** Mahima Advilkar

## Context

Revenue Sentinel has eight platform layers and nine logical agents. The obvious instinct
is to give each layer a service — ingestion, orchestration, policy, execution, cost — and
the architecture diagram would look impressive.

It would also be wrong for this project. One developer, eleven working sessions, and a
requirement that the repository stay runnable at the end of every milestone (rule 16).
Distributed systems buy independent scaling and independent deployment at the cost of
network partitions, distributed transactions, service discovery, and local development
complexity. None of those benefits apply at this scale; all of those costs do.

The real risk of a monolith is not performance — it is that the boundaries rot, and by the
time extraction is wanted the layers have grown into each other.

## Decision

Build a **modular monolith**: one installable Python package, one FastAPI process, one
Next.js app, one PostgreSQL database. Each platform layer maps to exactly one Python
subpackage, and **layer boundaries are enforced mechanically by `import-linter` in CI**.

Six rules are checked on every commit (see
[`system-architecture.md`](../system-architecture.md) §3). The two that carry the most
weight:

- `analytics/` may not import `intelligence/` — calculators can never reach an LLM.
- `execution/` may only act on a `PolicyDecision` — side effects cannot bypass governance.

## Alternatives considered

**Microservices from day one.** Rejected: multiplies operational surface, breaks
local-first development, and would consume most of the eleven sessions on infrastructure
rather than on the thing being demonstrated. The architecture would be more impressive to
describe and less impressive to run.

**A single flat package with no enforced boundaries.** Rejected: this is the failure mode
that gives monoliths their reputation. Without a mechanical check, "keep business logic out
of routes" is a preference that survives until the first deadline.

**Hexagonal architecture with a full DI container.** Rejected as over-engineering for this
size. We keep ports and adapters where they earn their place (integrations, LLM client,
graph runtime) and use plain constructor injection elsewhere.

## Consequences

**Easier:** one process to run and debug; refactoring across layers is a normal edit;
transactions are ordinary database transactions; a fresh clone works.

**Harder:** no independent scaling; a crash takes everything down; deploys are all-or-nothing.

**We now owe:** the `import-linter` contract file must be maintained as packages are added.
A new package without a rule is a boundary that is not being checked, and that is a silent
regression. Adding a package and its contract must happen in the same commit.

## Revisit when

Any of: workflow runs exceed a single process's throughput; more than one consumer needs
the GTM MCP server; independent deploy cadence per layer becomes a real constraint; or
event volume exceeds what a single-writer Postgres can absorb. See
[`scaling-roadmap.md`](../scaling-roadmap.md) §1 for the extraction seams already in place.
