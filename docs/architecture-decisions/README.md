# Architecture Decision Records

Significant or non-obvious technical decisions are recorded here, with the alternatives
that were rejected and why (rule 18). Accepted shortcuts and known limitations belong here
too — an ADR is where tribal knowledge goes to become reviewable.

---

## Index

| ADR | Title | Status | Date |
|---|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith with enforced layer boundaries | Accepted | 2026-08-01 |
| [0002](0002-langgraph-orchestration-boundary.md) | LangGraph orchestrates; it is not the architecture | Accepted | 2026-08-01 |
| [0003](0003-deterministic-vs-llm-boundary.md) | Deterministic code owns money, policy, and ranking | Accepted | 2026-08-01 |
| [0004](0004-simulated-integrations.md) | Simulated integrations behind real ports | Accepted | 2026-08-01 |
| [0005](0005-policy-and-approval-model.md) | Deterministic policy tiers with human approval | Accepted | 2026-08-01 |
| [0006](0006-postgres-as-event-substrate.md) | PostgreSQL as the event substrate; no broker in v1 | Accepted | 2026-08-01 |
| [0007](0007-offline-fixture-demo-mode.md) | Offline fixture demo mode is the default | Accepted | 2026-08-01 |
| [0008](0008-banded-risk-factors.md) | Stall risk and usage offset are banded lookup tables | Accepted | 2026-08-02 |
| [0009](0009-synchronous-persistence.md) | Synchronous SQLAlchemy for persistence | Accepted | 2026-08-02 |
| [0010](0010-enforcing-no-any-by-ast-check.md) | "Zero `Any`" is enforced by an AST check | Accepted | 2026-08-02 |
| [0011](0011-incident-severity-bands.md) | Incident severity is banded weighted pipeline value | Accepted | 2026-08-03 |
| [0012](0012-in-memory-checkpointer.md) | `InMemorySaver` in Session 3 | Accepted (**amended** by [0016](0016-durable-business-state-resume.md)) | 2026-08-04 |
| [0013](0013-hand-authored-llm-fixtures.md) | Hand-authored LLM fixtures as the Session 3 bootstrap | Accepted | 2026-08-04 |
| [0014](0014-sync-async-mcp-boundary.md) | The sync/async boundary sits inside `mcp/client.py` | Accepted | 2026-08-05 |
| [0015](0015-policy-as-a-pure-function.md) | Policy is a pure function over a versioned rule set | Accepted | 2026-08-06 |
| [0016](0016-durable-business-state-resume.md) | Durable business-state resume, not framework checkpoints | Accepted | 2026-08-08 |
| [0017](0017-idempotency-at-least-once.md) | Idempotency by claimed key; at-least-once with an explicit unknown | Accepted | 2026-08-08 |
| [0018](0018-claimed-identity-no-authentication.md) | Approval identity is claimed, not authenticated | Accepted | 2026-08-08 |
| [0019](0019-pre-spend-budget-enforcement.md) | Pre-spend budget enforcement by conservative admission control | Accepted | 2026-08-08 |
| [0020](0020-versioned-pricing.md) | Pricing is versioned data, not constants | Accepted | 2026-08-08 |
| [0021](0021-deterministic-structural-evaluation.md) | Evaluation is deterministic and structural; no LLM judge in v1 | Accepted | 2026-08-08 |
| [0022](0022-read-only-dashboard.md) | The dashboard is read-only until authenticated identity exists | Accepted | 2026-08-08 |
| [0023](0023-openapi-generated-typescript-contract.md) | OpenAPI-generated TypeScript is the frontend/backend contract | Accepted | 2026-08-09 |
| [0024](0024-partial-fixture-freshness-digest.md) | Fixture freshness is checked by a deliberately partial digest | Accepted | 2026-08-08 |
| [0025](0025-human-attested-indeterminate-reconciliation.md) | `INDETERMINATE` actions are reconciled by an attested human | Accepted | 2026-08-09 |
| [0026](0026-global-budget-concurrency-boundary.md) | Concurrent `GLOBAL` budget enforcement stays a bounded, documented limitation | Accepted | 2026-08-09 |

---

## Format

Each record uses the same five sections:

```markdown
# ADR-NNNN: Title

**Status:** Proposed | Accepted | Superseded by ADR-MMMM
**Date:** YYYY-MM-DD
**Deciders:** who

## Context
The forces at play. What made this a decision rather than a default.

## Decision
What we are doing, stated plainly.

## Alternatives considered
Each option, with the reason it was not chosen.

## Consequences
What becomes easier, what becomes harder, and what we now owe.

## Revisit when
The concrete signal that should reopen this decision.
```

---

## Rules

1. **ADRs are immutable once accepted.** To change a decision, write a new ADR that
   supersedes the old one and update the old one's status. Never edit history.
2. **Number sequentially**, zero-padded to four digits.
3. **"Revisit when" is mandatory** and must name an observable trigger, not a feeling.
   "When event volume exceeds single-writer Postgres throughput" is a trigger; "when it
   feels slow" is not.
4. **Record the shortcuts too.** An accepted limitation with a written rationale is
   engineering; the same limitation undocumented is debt.

[`../../DECISIONS.md`](../../DECISIONS.md) holds the running log of smaller decisions that
do not warrant a full record.
