# ADR-0022: The dashboard is read-only until authenticated identity exists

**Status:** Accepted
**Date:** 2026-08-08
**Deciders:** Mahima Advilkar

## Context

Session 6 built the approval mechanism: expiry evaluated on read, self-approval refused,
and a gate that will not execute a Tier 2 action without an `ApprovalRequest` row whose
status is `APPROVED`. All of it works, and all of it is tested.

What does not exist is **authentication**. ADR-0018 recorded the consequence plainly:
`--as` is a *claimed* identity, nothing verifies it, and anyone who can run the CLI can
claim any actor. Self-approval prevention compares two strings — it stops an accident,
not an impersonation.

Session 9 adds a browser. The obvious next step is an **Approve** button, and it is the
wrong one.

## Decision

**The dashboard renders approvals; it does not decide them. Every endpoint is a GET, and
the only mutation surface remains the CLI.**

The approval inbox shows the request, its effective status, its expiry, and **the exact
command to run**. It carries a note stating that approval identity is not authenticated
in v1.

### Why a button is worse than no button

A CLI invocation is honest about what it is: a command run by whoever holds the shell.
Nobody reading `rs approve APR-001 --as usr:revenue-lead` in a terminal believes the
system verified who typed it.

A button in a browser communicates the opposite. Buttons imply sessions; sessions imply
users; users imply that `decided_by` means something. It would be a **control-shaped
thing with no control behind it** — and unlike the CLI, it would be reachable by anything
that can route to the service, with no shell access required.

So the button would not merely fail to add safety. It would actively mislead, in a
project whose main claim is that it does not overstate what it does (rule 5).

### Visibility is safe; mutation is not

Reading is a different risk profile from writing. Showing what is pending, who requested
it, when it expires, and what it would do adds no authority to anyone. It makes the
governance layer legible, which is most of what a dashboard is for at this stage.

Enforcement is structural rather than remembered: a test parses the OpenAPI schema and
fails if any POST, PUT, PATCH, or DELETE endpoint appears outside `/ingest`. A future
contributor who adds an approval mutation without reading this ADR gets a red build
rather than a code review that might not catch it.

## Alternatives considered

**An unauthenticated approve endpoint with a warning banner.** Rejected. A warning does
not change what the endpoint does, and the people most likely to act on the button are
the least likely to read the banner above it.

**A shared secret or basic auth on the endpoint.** Rejected — worse than an honest claim.
One credential for every approver makes `decided_by` unattributable, so the audit trail
would record a fiction. An unverified string at least does not pretend.

**OS username via `getpass.getuser()`, forwarded from a local UI.** Rejected as false
precision: trivially overridden, and it would *look* authenticated in the audit trail
while being exactly as unverified as `--as`.

**Deferring the dashboard entirely until auth exists.** Rejected. The read surface is
independently useful and carries no authorisation risk; blocking it on an identity
provider would delay visibility for a reason that does not apply to reading.

## Consequences

**Easier.** The dashboard ships without an identity provider, a session model, or an
authorisation model. Approval keeps one surface, so there is one place where the rules
live and one place to audit.

**Harder.** Approving requires a terminal. That is genuine friction for the Account
Executive persona in `docs/product-requirements.md` §2, and it is friction chosen
deliberately over a false affordance.

**We now owe** the statement in the UI itself, not only in documentation: the approval
inbox says that identity is unauthenticated and that approval is CLI-only. A dashboard
that quietly omitted that would recreate the impression the missing button avoids.

## Revisit when

**Real authenticated session identity exists, with an auditable actor binding** — a
verified principal on the request, recorded on the approval, and reproducible after the
fact. That is the single trigger. It is not "when the button is requested", and it is not
"when a reverse proxy sits in front of the service": network-level access control says
where a request came from, not who made it.

At that point ADR-0018's claimed-identity limitation is also resolved, and the two
decisions should be revisited together rather than separately.
