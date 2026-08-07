# ADR-0015: Policy is a pure function over a versioned rule set

**Status:** Accepted
**Date:** 2026-08-06
**Deciders:** Mahima Advilkar

## Context

ADR-0005 committed to deterministic policy tiers with human approval. Session 5 had to
build it, and the shape was not obvious: a policy engine is exactly the sort of
component that accretes a session handle, a clock, a feature flag, and eventually a
model call, until "deterministic" describes its intent rather than its behaviour.

Three forces made the shape worth deciding rather than defaulting into.

**A decision has to be reproducible later.** `policy_evaluations` records a decision,
its tier, its matched rules, and a `policy_version`. That record is only worth having if
someone can take the same inputs a year from now and get the same answer under that
version. An engine that read a database or a clock could not offer that.

**The engine's refusals are the product.** The interesting output is not ALLOW, it is
DENY and REQUIRE_APPROVAL. Those need to be testable exhaustively and cheaply, which
means testable without a database.

**Untrusted content is one hop away.** Interventions are drafted by a model from
evidence that is adversarial by assumption (rule 14). If the engine could read an
intervention's rationale, an injected instruction would have a surface to argue with.

## Decision

**`governance/policy_engine.evaluate(request) -> PolicyOutcome` is a pure function. It
performs no I/O, reads no clock, holds no state, and considers no free text.**

- `PolicyRequest` carries only `action`, `target_ref`, `fields_changed`, and `actor`.
  There is deliberately no rationale field and no session. The model's prose reaches the
  engine nowhere.
- Classification lives in `governance/tiers.py` as data: `MATERIAL_OPPORTUNITY_FIELDS`
  is transcribed verbatim from `docs/security-model.md` §3, and a test asserts the two
  still agree. A definition that lives in prose and is re-interpreted in code drifts.
- Tier → decision lives in `governance/rules.py` as a read-only mapping, so the rules
  can be read without reading the code, and cannot be reconfigured at runtime behind a
  `policy_version` that would then be a lie.
- **Default-deny is a `.get` with a denying default, not a `case _`.** An exhaustive
  `match` makes the default branch dead code, so an enum member added and forgotten
  falls through to whichever branch happened to be last. With a mapping it is denied,
  which is what default-deny is supposed to mean.
- **Escalation is `max()`.** `RiskTier` is an `IntEnum` for exactly this. When several
  rules match, the highest tier wins and every matched rule is reported.
- `DeterministicPolicyEngine` adapts the pure function to the `PolicyEngine` Protocol
  `mcp/gate.py` already expects. **The gate is unchanged**, including its rule that a
  write with *no* engine bound raises. Session 5 supplies an engine to bind; it does not
  loosen what happens when none is.

**Deciding and acting stay in different modules.** The engine returns an outcome and
does nothing with it. In Session 5 nothing executes at all — the four write tools remain
unwired from the graph, and `run_investigation` still binds `policy=None`.

## Alternatives considered

**A rules DSL or a rules table in the database.** Rejected for v1. It moves policy from
something a reviewer reads in one file to something they have to query, and it makes
`policy_version` much harder to mean anything. The moment rules need to differ per
tenant, this becomes the right answer — see *Revisit when*.

**A class with injected dependencies (`PolicyEngine(session, clock)`).** Rejected. It
buys nothing here and costs the property the whole design rests on: a test suite that
covers every tier without a fixture, and a decision that can be recomputed from its
recorded inputs.

**Letting the engine read the intervention's rationale to classify better.** Rejected
firmly. It is the single most attractive way to make the classifier "smarter" and the
single most direct route from a prompt injection to an authorised action.

**Classifying with an exhaustive `match` and relying on mypy for coverage.** Tempting,
because a forgotten enum member becomes a type error. Rejected because the runtime
guarantee matters more than the build-time one: a member added by someone who silences
the type error should still be denied.

## Consequences

**Easier.** Every tier, every boundary, and every escalation path is a unit test with no
database. The golden scenario's three outcomes are reproducible on any machine. Adding a
tier or a rule is a change to a table with an obvious diff.

**Harder.** Policy cannot depend on anything the request does not carry — no "deny if
this account is in a regulated industry" without first widening `PolicyRequest`
deliberately. That friction is the feature.

**We now owe** two things. `MATERIAL_OPPORTUNITY_FIELDS` and `docs/security-model.md`
§3 must be changed together; the test that compares them is what enforces it. And
`policy_version` must be bumped whenever a rule changes, or a past decision will be read
against rules that did not produce it.

**Accepted limitation.** `approval_requests` has no `requested_by` column, so the
requesting actor is recorded in `decision_note` as `requested_by=<actor>` and read back
by `approvals.requested_by`. Self-approval rejection depends on that string. It works and
it is tested, but it is a workaround: the column belongs in the schema, and adding it is
a Session 6 migration rather than a schema change smuggled into a session that promised
not to execute anything.

## Revisit when

1. **Rules must differ per tenant, per region, or per customer.** A pure function over
   one module-level table cannot express that, and the rules table becomes correct.
2. **A policy decision needs state** — rate limits, "no more than N approvals per day",
   anything with memory. That is a genuinely different component and should not be bolted
   onto `evaluate`.
3. **Someone proposes giving the engine the intervention text.** Not a trigger to change
   the design — a trigger to re-read this ADR and the security model together.
