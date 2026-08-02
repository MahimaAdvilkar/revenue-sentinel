# ADR-0003: Deterministic code owns money, policy, and ranking

**Status:** Accepted
**Date:** 2026-08-01
**Deciders:** Mahima Advilkar

## Context

"Nine agents" invites an obvious reading: nine LLM calls, one per agent. That reading
produces a system where the pipeline-impact figure, the risk classification, and the
recommendation ranking are all model output — and therefore all unreproducible,
untestable, and unexplainable.

Three of the outputs this system produces are ones a revenue leader will act on and a
finance team may audit: a dollar figure, a policy decision, and a ranked recommendation.
None of those can be "usually right."

## Decision

**Draw an explicit line between what a model does and what code does, and enforce it
mechanically.**

Models: classify, extract, summarize, plan, hypothesize, explain, draft.
Code: arithmetic, thresholds, scoring, ranking, policy, budgets, idempotency.

Applied to the nine agents, only **four are LLM-backed**:

| LLM-backed | Deterministic |
|---|---|
| Investigation Planner | Signal Agent |
| Research Agent (tool selection) | Policy & Risk Agent |
| Revenue Analyst — *hypotheses only* | Revenue Analyst — *impact calculation* |
| Strategy Agent — *drafting only* | Strategy Agent — *ranking* |
| | Execution Agent |
| | Evaluation Agent |
| | Cost Governor |

Three enforcement mechanisms, in order of strength:

1. **`import-linter` rule R3:** `analytics/` may not import `intelligence/`. A calculator
   physically cannot reach a model.
2. **Tool boundary:** the Revenue Analyst cannot compute impact — it can only call
   `analytics_calculate_pipeline_impact`, which executes tested Python.
3. **Ledger assertion:** the `no_llm_arithmetic` evaluation check queries `model_calls` and
   fails if any is attributed to a node in the deterministic set.

Mechanism 1 is a build failure, mechanism 2 is an architectural impossibility, and
mechanism 3 is a runtime proof. The claim is not documented — it is checked three ways.

## Alternatives considered

**All nine agents LLM-backed.** Rejected: the impact figure would vary between runs on
identical input. A revenue number that changes when you re-run it is not a number.

**LLM computes, code verifies.** Rejected: if code can verify the answer, code can produce
it — the model call is pure cost and latency for a result that must be recomputed anyway.

**LLM with a calculator tool, model interprets the result.** Partially adopted — this is
exactly mechanism 2. The distinction is that the model never *transforms* the returned
figure. It may explain $32,130; it may not round it, adjust it, or restate it as
"approximately $32K" in a field the dashboard renders as currency.

## Consequences

**Easier:** the impact calculation is unit-testable to the cent; policy decisions are pure
functions; the demo is reproducible; cost drops because fewer calls are made; every number
shown can be recomputed by hand from stored inputs.

**Harder:** more code to write and maintain; calculators cannot flex to unusual cases the
way a model would; each new scenario needs its own tested calculator rather than a prompt.

**We now owe:** `impact_assessments.inputs` must store every input to every calculation, so
that a figure in the UI can always be traced to its arithmetic. A calculator whose inputs
are not recorded is as opaque as a model call.

## Revisit when

A calculation is genuinely too context-dependent to express as a tested function — for
example, a qualitative risk factor that depends on reading the tone of a support thread. In
that case the correct move is not to let the model do arithmetic: it is to have the model
produce a *typed, bounded, validated input* (an enum or a clamped score) that the
deterministic calculator then consumes. The line moves; it does not blur.
