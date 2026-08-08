# ADR-0021: Evaluation is deterministic and structural; no LLM judge in v1

**Status:** Accepted
**Date:** 2026-08-08
**Deciders:** Mahima Advilkar

## Context

Session 8 had to answer "does this system do what it promised?" — which is a different
question from "do the tests pass". Unit and integration tests check components and flows.
The rubric checks *one complete golden run against the requirements*, and it is the only
suite that fails when the system works but does not do what was claimed for it.

The reflexive design for agent evaluation is an LLM judge: show a model the output, ask
it to score. That is the wrong instrument here, for a reason specific to this project
rather than a general objection.

**This system has never made a live API call.** Its fixtures are hand-authored
(ADR-0013). A judge would therefore need either a real budget — which the project does
not have and has repeatedly declined to spend — or its own hand-authored fixture. The
second option is **circular**: a fixture I wrote, grading output produced from a fixture I
wrote, against criteria I chose. It would produce a number, the number would be high, and
it would mean nothing.

The alternative turned out to be available. Every requirement in
`docs/evaluation-strategy.md` §4 is decidable from rows the system already writes.

## Decision

**All v1 evaluation is deterministic and decided from persisted state. No model is
consulted — not by a check, not by the reporter.**

Fifteen workflow checks, six named injection cases, one cross-cutting security invariant,
and five policy-bypass checks. Every one is a SQL question. `make eval` costs
`$0.000000`, and that is a true figure rather than a rounding.

### Recomputation, not self-comparison

`impact_computed_deterministically` re-runs `calculate_pipeline_impact` from
`impact_assessments.inputs` and compares to the cent. Reading the stored figure back would
prove only that it agrees with itself: if persistence ever drifted from the calculator,
the self-comparison would still pass. This is the difference between checking a value and
checking the *process that produced it*.

### Invariants, not fixture values

`hypotheses_cite_real_evidence` asserts that every citation resolves through the join
table — true for any fixture. A check asserting "H1 cites EV-002" would grade the fixture
rather than the system, and would need rewriting every time a fixture changed. Where a
figure genuinely *is* the contract (the golden $108,000 / $32,130), the check says so
explicitly rather than pretending to be general.

### The negative corpus is a requirement, not a nicety

**A rubric nobody has seen fail is a rubric nobody knows works.** A check with an inverted
comparison, or a query that silently matches nothing, sails through a green run. So every
one of the fifteen checks has a test that deliberately breaks the property it guards and
asserts the check fails.

Where a database constraint makes the strongest corruption **unrepresentable**, the test
asserts the constraint instead and documents why — `UNIQUE (idempotency_key)` means a
duplicate action cannot be inserted, and the database refusing it *is* the proof. The goal
is evaluator credibility, not test symmetry, and weakening a constraint to manufacture a
failure would trade a real guarantee for a cosmetic one.

### Schema constraints are part of the security proof

Several guarantees are enforced by the schema rather than by code, and the evaluation
treats that as stronger evidence, not weaker:

- `action_records.authorized_by` → `policy_evaluations` makes an unauthorised effect
  unrepresentable.
- `UNIQUE (idempotency_key)` makes a duplicate effect unrepresentable.
- `hypothesis_evidence`'s foreign keys make a fabricated citation unrepresentable.
- `TrustLevel` has exactly one member, so there is no code path that marks ingested
  content trusted.

A check whose failure mode the database prevents is a check that has already succeeded.

### What "prompt-injection contained" means

**Containment does not mean the model ignored the instruction.** A check asserting that
would pass because a particular model happened to comply, would start failing on a model
upgrade without anything having got worse, and — worst — would credit obedience for a
guarantee that must not depend on it.

Containment is four structural facts, in increasing order of importance:

1. the payload is persisted `trust_level = untrusted`;
2. it is rendered only inside escaped `<evidence>` boundaries it cannot break out of, and
   cannot forge an attribute;
3. it produced no policy decision it was not entitled to;
4. **it caused no effect** — no `action_records` row without valid authorisation, no tool
   call outside the permitted route, and no invocation of a capability that does not
   exist.

Layers 1–2 reduce *likelihood*. Layers 3–4 bound *consequence*, and consequence is the one
that has to hold. A successful injection that changes nothing is a contained injection.

### Append-only evaluation history

Every `make eval` invocation creates a new `evaluation_runs` row. **A failed evaluation is
never overwritten by a later passing one.** The existing
`UNIQUE (evaluation_run_id, check_name)` then guarantees exactly one result per check
within an attempt, without constraining how many attempts exist.

Overwriting would make the history a current-status flag, and the question evaluation
history exists to answer is "when did this start failing?" — which a flag cannot.

`suite_version` carries the evaluator version, so a result can be read against the
evaluator that produced it. No migration was needed; the schema already had the field.

## Alternatives considered

**An LLM judge for subjective quality.** Rejected for v1 — circular without a real budget,
as above. Not rejected in principle; see *Revisit when*.

**Asserting golden output verbatim.** Rejected: it grades the fixture, and every fixture
change becomes an evaluation change, which trains the reader to update expectations rather
than investigate them.

**Sampling many synthetic scenarios for precision/recall.** Rejected as a false claim.
There is one hand-authored scenario. Generating ninety-nine more from the same generator
would measure the generator.

**Evaluating inside the existing test suite.** Rejected: the rubric answers a different
question and should be able to fail while every unit test passes. `make eval` is separate
and exits non-zero, so CI treats it as a build failure.

## Consequences

**Easier.** Evaluation costs nothing, runs offline, and is reproducible. Every result is
explainable from rows. The negative corpus means a failing check is trusted when it fires.

**Harder.** Nothing subjective is measured. Whether a hypothesis is *insightful* or a draft
email is *well written* is invisible to this suite, and those are real qualities a reader
of the dashboard would care about.

**We now owe** honesty about what is not measured. One golden scenario measures **no**
production precision, recall, or intervention effectiveness, and the documentation must not
imply otherwise.

## Revisit when

1. **A subjective quality dimension matters enough to gate on** — message tone,
   hypothesis insightfulness, recommendation usefulness — and cannot be expressed as a
   deterministic invariant. Then a judge is the right instrument, and it needs a **real
   evaluation budget** and a **recorded judge configuration** (model, version, prompt
   digest, effort) stored alongside each score, so a judged result is as reproducible as a
   deterministic one.
2. **Real outcome feedback exists** — did the intervention work? — at which point
   effectiveness becomes measurable and stops being a thing this document declines to
   claim.
3. **More than one scenario exists**, making detector precision and recall meaningful
   rather than a statement about a single fixture.
