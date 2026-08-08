# ADR-0018: Approval identity is claimed, not authenticated

**Status:** Accepted
**Date:** 2026-08-08
**Deciders:** Mahima Advilkar

## Context

Session 6 needs a human to approve a Tier 2 action. The approval is load-bearing: it is
the difference between a system that drafts a customer email on its own authority and one
that does not.

It is therefore tempting to present the approval mechanism as a control. It is not one
yet, and the gap needs writing down rather than glossing.

**There is no authentication anywhere in this system.** No users table with credentials,
no sessions, no tokens, no SSO. Adding real identity means choosing an identity provider,
a session model, and an authorisation model -- work that belongs with the dashboard in
Session 9, done once, rather than improvised here to make a CLI look official.

## Decision

**Approvals are decided at the CLI, with a claimed identity, and the system says so.**

```
uv run rs approve APR-001 --as usr:revenue-lead
```

- `--as` is a string the caller supplies. Nothing verifies it.
- Every approval prints a warning stating that plainly.
- `approval_requests.requested_by` and `decided_by` record what was *claimed*.
- **No HTTP endpoint is exposed.** An unauthenticated `POST /approvals/{ref}/approve`
  would be strictly worse than no endpoint: it looks like a control, is reachable by
  anything that can route to the service, and invites a frontend to be built against it.

### What self-approval prevention actually buys

`decide()` refuses when `requested_by == decided_by`. That prevents the **accident** --
an operator approving a request their own automation raised -- and it is worth having.

It does **not** prevent impersonation. Anyone who can run the CLI can pass any string.
The check is a guardrail, not a boundary, and the docs must not describe it as one.

## Alternatives considered

**A CLI plus an unauthenticated endpoint.** Rejected, above.

**Basic auth or a shared secret on an endpoint.** Rejected: a shared secret is one
credential for all approvers, so `decided_by` becomes unattributable and the audit trail
records a fiction. Worse than an honest claim.

**OS username via `getpass.getuser()`.** Rejected as false precision -- trivially
overridden by environment, and it would *look* authenticated in the audit trail while
being exactly as unverified as `--as`.

**Defer approvals entirely until auth exists.** Rejected: the approval *mechanism* --
expiry, self-approval refusal, the gate that will not execute without it -- is the part
worth building and testing now. Only identity verification is deferred.

## Consequences

**Easier.** Session 6 ships a working approval loop with no auth infrastructure, and
Session 9 designs identity once with a real UI in front of it.

**Harder.** The approval audit trail is honest about *what was claimed*, not *who acted*.
Any statement about this system's controls has to carry that qualifier.

**We now owe** an explicit, repeated statement -- in the CLI output, the README, the
capability matrix, and the security model -- that this is **not production identity
verification**. Understating it once would make every other honesty claim in this project
worth less.

## Revisit when

1. **The dashboard lands (Session 9)** and there is a real session to attribute an
   approval to.
2. **Anyone proposes an approval HTTP endpoint** -- not a trigger to build one, a trigger
   to read this ADR first.
3. **The system is pointed at a real integration.** Claimed identity is tolerable when
   every effect is SIMULATED; it is not once an approval causes a real customer email.
