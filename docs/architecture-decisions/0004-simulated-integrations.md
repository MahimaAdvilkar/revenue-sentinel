# ADR-0004: Simulated integrations behind real ports

**Status:** Accepted
**Date:** 2026-08-01
**Deciders:** Mahima Advilkar

## Context

The system needs six external integrations: CRM, product usage, engagement, support,
enrichment, and messaging. Connecting any of them for real would require OAuth flows,
sandbox accounts, rate-limit handling, and — critically — a decision about whose data goes
in. Employer data and real customer data are both out of the question for a public
portfolio repository.

But a demo backed by mocks has a credibility problem. Reviewers have seen projects where
"integrations" means a hardcoded dictionary, and the honest response to that is suspicion.

The question is not whether to simulate. It is how to simulate in a way that is
*architecturally* real even though the data is not.

## Decision

**Deterministic simulated adapters behind production-shaped port interfaces, labelled as
simulated everywhere they appear.**

Four commitments:

1. **The seam is architectural, not cosmetic.** Ports are `Protocol` definitions in
   `integrations/ports/`. Simulated implementations live in `integrations/simulated/`. A
   real adapter would be a sibling directory implementing the same protocol — no call site
   changes.
2. **Status is data, not documentation.** Every adapter module declares
   `INTEGRATION_STATUS = "SIMULATED"`. The MCP server reads it and stamps it on every tool
   result. Source-mirror tables carry `is_simulated BOOLEAN NOT NULL DEFAULT TRUE`. The
   dashboard renders a badge from that column. There is no configuration that makes a
   simulated adapter claim to be real.
3. **Every adapter documents its real counterpart.** A required
   *"What changes when this becomes real"* docstring section naming the specific API, auth
   model, rate limits, pagination, and the fields that would differ.
4. **Data is deterministic and obviously synthetic.** Fixed seed, byte-identical output,
   fictional companies (`Northwind Logistics`), `@example.com` addresses.

Commitment 3 is what turns simulation from an excuse into a design artifact. Anyone can
write a mock; describing precisely what the real integration would require demonstrates you
understand the integration.

## Alternatives considered

**Connect real HubSpot and Gmail sandboxes.** Rejected: consumes days on OAuth and sandbox
setup, introduces credentials into a public repository, makes the demo dependent on network
and third-party availability, and risks real data exposure. High cost, and it demonstrates
integration plumbing rather than agent architecture.

**Inline mocks inside the tool handlers.** Rejected: no seam, so no migration path, and
exactly the pattern that earns reviewer suspicion.

**A recorded HTTP cassette layer (VCR-style) against real APIs.** Rejected for v1: requires
real credentials to record, and the cassettes would embed real account structures. Worth
reconsidering once a sandbox exists.

## Consequences

**Easier:** the demo is offline, fast, free, and reproducible; no credentials anywhere; no
third-party dependency; tests run everywhere including CI.

**Harder:** real-world messiness is absent — no rate limits, no partial failures, no schema
drift, no pagination edge cases. The simulated adapters are *too well behaved*, and the
first real integration will surface problems this design has not been tested against.

**We now owe:** the simulated adapters must inject at least some realistic failure —
latency, transient errors, missing fields — so the retry and error-handling paths are
exercised rather than theoretical. An adapter that never fails does not test the executor.

## Revisit when

A sandbox account and explicit approval both exist for a specific integration, and the
vertical slice is complete. First candidate is enrichment: smallest surface, simple API-key
auth, and it makes the enrichment-cost-anomaly scenario real. Never before the slice works
(rule 2), and never without approval (rule 20).
