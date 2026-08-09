# ADR-0023: OpenAPI-generated TypeScript is the frontend/backend contract

**Status:** Accepted
**Date:** 2026-08-09
**Deciders:** Mahima Advilkar

## Context

Session 9 adds a TypeScript frontend to a Python backend. The two now have to agree about
the shape of eight JSON payloads, and there are only two ways that agreement can be
maintained: by hand, or by generation.

By hand means writing `interface CostSummaryResponse { total_cost: string; ... }` in
TypeScript and keeping it in step with the Pydantic model. It works on the day it is
written. It fails the way all duplicated definitions fail — quietly, some weeks later,
when someone renames `at_risk_value` in the backend and the frontend keeps compiling
because *its* copy still says `at_risk_value`. The screen renders `undefined`, which
React displays as nothing, and an empty cell looks like a deal with no money at risk
rather than a bug.

That failure mode is especially bad here. This project's claims are numeric — `$108,000`
weighted, `$0.000000` spent — and a silently blank figure is worse than a crash.

## Decision

**FastAPI's OpenAPI schema is the source of truth. TypeScript types are generated from it
and are the only description of API responses the frontend has.**

- `scripts/export_openapi.py` writes `apps/web/generated/openapi.json`.
  `openapi-typescript` turns that into `apps/web/generated/api.ts`.
  `make generate-api-types` runs both.
- `apps/web/lib/api.ts` re-exports aliases into the generated schema
  (`components["schemas"]["CostSummaryResponse"]`) and contains **no hand-written
  response interfaces**. Every screen imports from there.
- Request paths are typed against `keyof paths`, so a typo or a removed endpoint is a
  compile error rather than a 404 found by a user.

**The schema is checked in**, not generated at build time from a live server. Two
reasons: a contract change then appears in the diff where a reviewer can see it, and the
frontend builds without a database and an API process running — which matters for CI and
for anyone cloning the repository.

Generation is deterministic: sorted keys, fixed indentation. Regenerating without a
backend change produces no diff, so a dirty `generated/` directory means the contract
genuinely moved.

### What this buys, demonstrated

It is not theoretical. Building the incident queue, `pnpm typecheck` rejected
`incident.account_name`, `incident.amount`, `incident.currency`, and
`incident.is_simulated` — because `IncidentSummary` published none of them. Four fields
the screen genuinely needed, caught before a single line of UI ran. The fix was to add
them to the API and regenerate, and the compiler confirmed the fix landed.

Hand-written interfaces would have accepted all four, and the queue would have shipped
with four blank columns.

## Alternatives considered

**Hand-maintained interfaces.** Rejected — the failure mode above, and it scales with
every endpoint added.

**Generating at build time from a running server.** Rejected: it makes the frontend build
depend on a live backend and a populated database, and a contract change becomes
invisible in review because nothing is committed.

**A shared schema language upstream of both** (protobuf, JSON Schema as source). Rejected
as premature. FastAPI already produces an accurate OpenAPI document from the Pydantic
models that are themselves the validation layer — introducing a third definition to sit
above both would add a translation step without removing one.

**`zod` schemas hand-written in the frontend for runtime validation.** Rejected for v1:
it duplicates the contract again, in a third place, to defend against a backend that is
already typed and tested. Worth revisiting if the API is ever consumed by something
outside this repository.

## Consequences

**Easier.** A backend rename breaks the frontend build immediately and precisely. Screens
consume one type definition that is provably what the server sends. Adding an endpoint is
regenerate-and-use.

**Harder.** The generated file must be regenerated when the API changes, and a
contributor who forgets gets a confusing error until they run `make generate-api-types`.
The command is documented in the README and in the Makefile help.

There is also a real constraint the generator imposed: `openapi-typescript` cannot express
a **recursive** schema through indexed access, so the recursive `JSONValue` behind
evidence content produced a type TypeScript refused to resolve. The fix was at the API
boundary — evidence `content` is published as a free-form object, which is a truthful
description of the payload and one a generator can express. The internal type is
unchanged. That is the shape of tax this decision charges: occasionally the contract must
be *expressible*, not merely correct.

**We now owe** regeneration as part of any API change, and the discipline that
`generated/` is never hand-edited. A hand-edit would survive exactly until the next
regeneration and would be the hardest possible bug to explain.

## Revisit when

1. **A second consumer appears** outside this repository, at which point runtime
   validation (`zod` or equivalent) starts earning its duplication, because the frontend
   can no longer assume the backend it was generated against.
2. **The generator cannot express something the API genuinely needs** — the recursive-type
   case above was resolved by narrowing at the boundary, but a case where narrowing would
   lose real information should reopen this rather than be worked around.
3. **Response shapes start differing per caller** (field selection, partial responses),
   which OpenAPI describes poorly and a query language describes well.
