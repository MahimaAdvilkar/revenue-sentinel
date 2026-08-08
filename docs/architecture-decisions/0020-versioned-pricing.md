# ADR-0020: Pricing is versioned data, not constants

**Status:** Accepted
**Date:** 2026-08-08
**Deciders:** Mahima Advilkar

## Context

A cost ledger is only worth having if a figure recorded months ago can be explained. That
requires knowing which prices produced it — and provider prices change. Anthropic's
Sonnet introductory rate ($2.00/$10.00 per MTok) expires 2026-08-31, after which the
standard rate applies.

If prices were constants in code, editing them would silently reprice every historical
entry. The ledger would still balance, and every stated figure would be wrong.

## Decision

**Prices are a versioned table, every entry records its version, and a published version
is never edited in place.**

- `PRICING_VERSION = "pricing/2026-08"`, stamped on every `cost_entries` row.
- Changing any price means publishing a **new** version, not editing numbers under an
  existing one. Past entries keep pointing at the prices that produced them.
- `cost_of()` is a **pure function** — no database, no client, no network. That is what
  lets the arithmetic be tested exhaustively without spending a cent, which matters
  because this project has never made a live API call (ADR-0013).
- An unpriced model **raises** rather than defaulting. A cost silently computed as zero
  for an unknown model is worse than a refusal.

**Provider prices are configuration, not model behaviour.** They belong to a contract with
a vendor, change on their schedule, and are exactly the kind of thing that should be
inspectable data rather than a literal buried in an expression.

### Precision

All arithmetic is `Decimal`; float is forbidden for money (`docs/data-model.md` §1).
Results quantize to **six decimal places** with `ROUND_HALF_EVEN`.

Six, because one small Haiku call costs a fraction of a cent: `$0.000150` rounds to
`$0.00` at two places, so a cents-precision ledger would report real spend as free.
`ROUND_HALF_EVEN` because it does not accumulate the upward bias of half-up across
thousands of entries.

**Migration 0007 exists for this.** `cost_entries.amount_usd` was already
`NUMERIC(12, 6)`, but `budgets.limit_usd` and `consumed_usd` were `NUMERIC(14, 2)` —
inherited from the money vocabulary used for pipeline figures, where cents are right.
Against microdollar costs that was wrong in both directions: a limit finer than a cent
could not be expressed, and accumulating `$0.000150` into two decimals discarded it. **A
budget that cannot see the spend charged against it is not a budget.** Found by a test
that set a limit one microdollar below a reservation and watched the call be admitted,
because the limit had rounded up to the next cent. The downgrade refuses rather than
truncating recorded spend.

### The Sonnet introductory rate

Deliberately **not** encoded. A price that changes on a date would make the same inputs
produce different figures depending on when the function ran — precisely what
`pricing_version` exists to prevent. The standard rate is in `pricing/2026-08`; if the
introductory period is ever relevant, it becomes its own published version.

### Caching

Cache reads are 0.1× base input price; writes 1.25× (5-minute TTL). Implemented and
tested as arithmetic. **No cache hit has ever been observed by this system** — the
multipliers are the documented mechanics, not a measurement.

## Alternatives considered

**Prices as module constants.** Rejected — editing them rewrites history.

**Prices in the database.** Rejected for v1: it moves a rarely-changing table into
migrations and admin tooling for no gain, and makes the pure function impure. Worth
revisiting if prices ever need to differ per deployment.

**Storing the computed unit price alongside every entry instead of a version.** Rejected
as redundant: the amount is already stored. The version answers the harder question —
*why* that amount.

## Consequences

**Easier.** Any historical figure is recomputable. Pricing is testable at $0 to the
microdollar. Adding a model is a table entry.

**Harder.** Every price change is a code change with a new version string, and someone
must remember that editing a published version is forbidden. The test suite does not
enforce that today.

**We now owe** a new version when the Sonnet introductory rate lapses on 2026-08-31, and
the standing caveat that **live provider token accounting has never been exercised** — the
prices are right, but nothing has confirmed the provider reports usage the way this code
expects to read it.

## Revisit when

1. **A live call is made** and reported usage can be checked against these assumptions.
2. **A price changes**, which is the first real exercise of publishing a new version.
3. **Per-deployment or negotiated pricing** is needed, at which point a database-backed
   table becomes the right answer.
4. **A provider prices something other than tokens** — per-request fees or cache storage —
   which this table cannot express.
