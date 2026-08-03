# ADR-0008: Stall risk and usage offset are banded lookup tables

**Status:** Accepted
**Date:** 2026-08-02
**Deciders:** Mahima Advilkar

## Context

[`../demo-scenario.md`](../demo-scenario.md) §2 pins two values as part of the golden
scenario:

```
stall_risk_factor = f(days_inactive=14, stage=Proposal) = 0.35
usage_offset      = g(usage_growth=0.40)                = 0.15
```

It never defines `f` or `g`. Session 1 had to, because
[`../../src/revenue_sentinel/analytics/pipeline_impact.py`](../../src/revenue_sentinel/analytics/pipeline_impact.py)
cannot produce `$32,130.00` without them.

This is precisely the risk the implementation plan names for Session 1: *"thresholds tuned
to make the fixture pass rather than to be defensible."* Two constants that happen to yield
the documented answer would satisfy the test suite and fail the interview.

There is also no data to fit against. Northwind Logistics is invented; there is no
historical win-rate corpus for a synthetic account, and there never will be.

## Decision

**Define both functions as explicit banded step tables, in
[`../../src/revenue_sentinel/analytics/risk_bands.py`](../../src/revenue_sentinel/analytics/risk_bands.py),
with the claim made for them stated narrowly in the module docstring.**

Stall risk is a base band selected by days of sales silence, multiplied by a stage factor,
capped at 0.85:

| Days inactive | Base | | Stage | Multiplier |
|---|---|---|---|---|
| 0–13 | 0.00 | | Discovery | 0.80 |
| 14–20 | 0.35 | | Proposal | 1.00 |
| 21–29 | 0.45 | | Negotiation | 1.20 |
| 30–44 | 0.55 | | | |
| 45+ | 0.65 | | | |

Usage offset is a band selected by week-over-week growth in `feature_events`, capped
at 0.20:

| Growth | Offset |
|---|---|
| < 0% | 0.00 |
| 0–19% | 0.05 |
| 20–39% | 0.10 |
| 40–79% | 0.15 |
| ≥ 80% | 0.20 |

Three properties are deliberate:

1. **The first stall band is 0.00.** Below the 14-day detection threshold a deal is not
   stalled, so asking for its stall risk returns nothing rather than a small positive
   number that would read as evidence.
2. **Declining usage earns no offset.** Falling engagement is not mildly reassuring, and a
   band that treated it as such would point the wrong way.
3. **Both are capped.** A stall factor of 1.00 would assert the deal is already dead, which
   silence alone does not establish. An uncapped offset would let enthusiastic product usage
   drive assessed risk to zero, and a buyer can use a product happily and still buy
   elsewhere.

**The claim made for these numbers is narrow and written down where the code lives.** They
are not empirically calibrated. What they are is deterministic, versioned (`risk_bands/v1`),
inspectable, and tested at every boundary — which is the property the system actually
depends on.

## Alternatives considered

**Two constants that produce the demo figure.** Rejected outright. It is the failure mode
the plan warned about, and it collapses the moment anyone asks what happens at 21 days.

**A fitted continuous curve** (exponential decay on inactivity, log on usage growth).
Rejected: it would *look* more rigorous while being less defensible, because the
coefficients could only have been chosen to hit the demo numbers. Sophistication without
data is decoration.

**Let the model estimate the risk factor.** Rejected under rule 9 and ADR-0003. The factor
multiplies a dollar figure; if a model produces it, the dollar figure is model output
wearing a calculator's clothes.

**Store the bands in the database as configuration.** Rejected for v1: it moves a tested,
version-controlled artifact into mutable state, and makes "which bands produced this
figure?" a question requiring a point-in-time query rather than a `bands_version` string.

## Consequences

**Easier:** every boundary is testable and tested (13 days versus 14, 39% versus 40%); a
revenue leader can read the table and argue with it; `impact_assessments.inputs` records
`bands_version`, so a figure computed under different rules stays identifiable; the whole
calculation is reproducible by hand.

**Harder:** step functions are discontinuous, so a deal at 20 days and one at 21 days differ
by ten points of assessed risk with nothing in between. That is a real artifact of the
choice, and it is visible rather than hidden.

**We now owe:** any change to a band is a `BANDS_VERSION` bump plus updated boundary tests,
and figures computed under the old version must remain interpretable through the stored
version string.

## Revisit when

Real outcome data exists — a corpus of opportunities with known inactivity windows, usage
trajectories, and win/loss results large enough to fit against. At that point the honest
move is to fit the curve, publish the fit statistics, and supersede this ADR. Until such
data exists, a fitted curve would be a more confident-looking version of the same guess.
