# ADR-0011: Incident severity is banded weighted pipeline value

**Status:** Accepted
**Date:** 2026-08-03
**Deciders:** Mahima Advilkar

## Context

[`../demo-scenario.md`](../demo-scenario.md) §2 states that `INC-001` opens at
severity `HIGH`. No document defined severity — not the data model, not the event
model, not the product requirements. The enum existed; the rule did not.

Session 2 had to supply one, because the incident service cannot write a row without
it. This is the same situation ADR-0008 addressed for the stall-risk factor: an
authoritative document asserts a value and leaves the function producing it
unspecified, which is exactly where a convenient constant gets quietly hard-coded to
make the demo come out right.

Severity is also load-bearing in a way that is easy to underrate. It orders the
incident queue, and from Session 9 it is the first thing a revenue leader sees. A
severity that cannot be explained is a queue that cannot be trusted.

## Decision

**Severity is a banded function of weighted pipeline value**, implemented in
[`../../src/revenue_sentinel/incidents/severity.py`](../../src/revenue_sentinel/incidents/severity.py)
and versioned as `severity_bands/v1`.

| Weighted value (`amount × probability`) | Severity |
|---|---|
| ≥ $250,000 | `CRITICAL` |
| ≥ $100,000 | `HIGH` |
| ≥ $25,000 | `MEDIUM` |
| < $25,000 | `LOW` |

Golden scenario: `180,000.00 × 0.60 = 108,000.00` → **HIGH**, which is what the demo
document already claimed.

Two implementation details are deliberate:

**It reuses the impact calculator's arithmetic.** `severity_for_weighted_value` calls
the same `to_cents` helper with the same `ROUND_HALF_UP` rule as
[`pipeline_impact.py`](../../src/revenue_sentinel/analytics/pipeline_impact.py). An
incident's severity and its impact assessment can therefore never disagree about the
weighted figure they are both derived from — which they would eventually do if each
rounded its own way.

**It is deliberately one-dimensional.** Severity does not fold in stage, account
segment, or how long the condition has persisted. Each of those would be another
uncalibrated weight, and a composite of four guesses is not more rigorous than one —
it is harder to explain and no more correct. "How much weighted pipeline is in play"
is a defensible proxy for how much attention an incident deserves, and the claim
stops there.

**The claim made for these numbers is narrow**, exactly as in ADR-0008: they are
deterministic, versioned, inspectable, and tested at both sides of every boundary.
They are **not** empirically calibrated, and no dataset exists that could calibrate
them for a synthetic account.

## Alternatives considered

**Severity from the raw amount, ignoring probability.** Rejected: a $500,000
opportunity at 5% is not a critical incident, and treating it as one would fill the
top of the queue with deals nobody expects to close.

**Severity from the at-risk figure** (`weighted × stall_risk × (1 − usage_offset)`).
Rejected as circular for v1: the at-risk figure is produced by the Session 3
investigation, and severity is needed at detection time, before any investigation has
run. It would also make severity depend on two more band tables, compounding
uncertainty rather than containing it.

**A composite score across amount, stage, inactivity, and segment.** Rejected. It
looks more sophisticated and is less defensible — four weights chosen without data,
where one at least admits what it is.

**Let the Signal Agent's model assign severity.** Not applicable and not desirable:
the Signal Agent is deterministic by design (ADR-0003), and severity ranks a queue of
dollar figures, which is arithmetic.

## Consequences

**Easier:** severity is explainable in one sentence to the person whose queue it
orders; it is computable at detection time with no dependency on investigation; both
sides of every boundary are tested; and a figure computed under different rules stays
identifiable through `SEVERITY_BANDS_VERSION`.

**Harder:** the bands are absolute dollar amounts, so they are implicitly tuned to a
mid-market book of business. An enterprise deployment where every deal exceeds
$250,000 would see everything as `CRITICAL` and the ranking would carry no
information. That is a real limitation of absolute thresholds, and it is visible here
rather than buried.

**We now owe:** any change to a band is a `SEVERITY_BANDS_VERSION` bump plus updated
boundary tests, and `docs/event-model.md` §5 must continue to state the table so the
rule stays discoverable from the authoritative document rather than only from code.

## Revisit when

Either of two observable triggers:

1. **The bands stop discriminating** — a deployment where more than roughly 80% of
   open incidents land in a single band. At that point the thresholds should become
   configurable per deployment, or relative to the book's own distribution
   (percentile-based) rather than absolute.
2. **Outcome data exists** — enough resolved incidents to measure whether severity
   predicted anything about which ones actually needed attention. That is the point
   at which a fitted or learned severity is honest rather than decorative, and this
   ADR should be superseded.
