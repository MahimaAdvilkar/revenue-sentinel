# ADR-0005: Deterministic policy tiers with human approval

**Status:** Accepted
**Date:** 2026-08-01
**Deciders:** Mahima Advilkar

## Context

The system proposes actions that touch a CRM and, potentially, a customer. Some of those
actions are trivially safe (create an internal task). Some are consequential (email a
customer, change a deal's close date). Some should not be possible at all (send email
directly, delete records).

The tempting design is to let the agent decide, guided by a well-written system prompt.
That design fails the moment ingested content contains instruction-shaped text — and rule
14 says to assume it does. It also fails a simpler test: you cannot write a unit test for
a prompt.

## Decision

**A deterministic policy engine classifies every proposed action into a risk tier, and
only the policy layer can authorize an external effect.**

Four tiers, defined in [`security-model.md`](../security-model.md):

| Tier | Meaning | Decision |
|---|---|---|
| 0 | Read / compute | ALLOW |
| 1 | Internal, reversible, no customer contact | ALLOW, audited |
| 2 | Customer-facing or **material** CRM change | REQUIRE_APPROVAL |
| 3 | Not a capability the system has | DENY |

Five properties make this real rather than nominal:

1. **The engine is a pure function** of `(intervention, policy_rules)` — no I/O, no model,
   fully unit-testable. Same input, same decision, always.
2. **"Material" is defined, not judged.** Writes to `amount`, `stage`, `probability`,
   `expected_close_date`, `owner_id`, or any delete. Everything else is not material. There
   is no room for interpretation, because interpretation is where injection lives.
3. **Ambiguity escalates.** When tier classification is uncertain, the engine chooses the
   higher tier. Caution is coded, not hoped for.
4. **`execution/` cannot act without a decision** — enforced by `import-linter` rule R4 and
   by the executor's signature, which takes a `PolicyDecision` or an approved
   `ApprovalRequest` and has no other entry point.
5. **Approval is a scoped, recorded event.** One approval authorizes exactly one
   `ActionRecord` via one `idempotency_key`. Never a blanket permission, never an implicit
   default, always with an actor and a timestamp.

Sending email is deliberately Tier 3 in v1: **the system can draft, but not send.** A
capability that does not exist cannot be misused, and the demo loses nothing.

## Alternatives considered

**LLM-based policy judgement** — ask a model whether an action is safe. Rejected: not
reproducible, not unit-testable, and directly vulnerable to injection. The component whose
job is to contain injection cannot itself be an injection target.

**Approval on everything.** Rejected: an agentic system where a human approves every action
is a form with extra steps. Tier 1 auto-execution is what makes it agentic; Tier 2 gating
is what makes it safe. Both are required.

**Approval on nothing, with rollback.** Rejected: a sent email cannot be rolled back. For
irreversible external effects, prevention is the only control.

**Policy as configuration from day one.** Rejected for v1 as premature; rules live in code
where they are typed and tested. Moving thresholds to config is recorded as known debt in
[`scaling-roadmap.md`](../scaling-roadmap.md).

## Consequences

**Easier:** every decision is testable, reproducible, and explainable; the audit trail
answers "why was this allowed?" with matched rule names; injection cannot escalate
privilege because privilege is not model-mediated.

**Harder:** policy rules must be maintained in code and a deploy is needed to change them;
a genuinely novel intervention type has no tier until someone assigns one; over-caution can
gate things a human would wave through.

**We now owe:** a default-deny for unclassified action types. An intervention whose
`action_type` matches no rule must be DENIED, not allowed. Fail-closed is the only safe
default for a policy engine, and it needs an explicit test.

## Revisit when

Approval volume makes the inbox unusable (see the scaling question in
[`scaling-roadmap.md`](../scaling-roadmap.md) §5) — at which point the answer is likely
finer-grained tiers and per-user delegation rules, not weaker gating. Also revisit if a
Tier 2 action proves reliably safe across many approvals and could earn Tier 1 with a
scoped operator enablement.
