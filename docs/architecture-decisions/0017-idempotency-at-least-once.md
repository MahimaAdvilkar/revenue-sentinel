# ADR-0017: Idempotency by claimed key; at-least-once with an explicit unknown

**Status:** Accepted
**Date:** 2026-08-08
**Deciders:** Mahima Advilkar

## Context

Session 6 lets the system perform effects: a CRM task, an email draft. Both are
SIMULATED, but the shape of the problem is the real one -- a workflow that can be
re-run, resumed, and retried must not produce the effect twice. "Re-running the workflow
cannot send a second email" is one of this project's louder claims.

`action_records.idempotency_key` has carried a `UNIQUE` constraint since the Session 1
baseline. What it did not have was a definition of the key, or an ordering rule for when
the row is written relative to the effect.

The ordering is where this usually goes wrong. Writing the record *after* the effect
succeeds is the obvious implementation and is broken: a crash in between leaves no
record, and the next run performs the effect again.

## Decision

**Claim the key before acting, and define it over business values only.**

```
key = sha256({version, incident_ref, action_type, target_ref, arguments_digest})
```

Deliberately **excluded**: `run_id`, `intervention_id`, every timestamp, `attempt_count`,
and every runtime-generated UUID. Excluding `run_id` is the load-bearing choice -- it
makes the key identify *the effect* rather than *the attempt*, so a second investigation
of the same incident collides instead of duplicating.

The sequence is:

1. `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING` with status `EXECUTING`
2. **commit the claim**
3. perform the effect through `mcp/`
4. record the outcome

The row is the lock; the `UNIQUE` constraint is what makes it real rather than advisory.

### At-least-once, and the explicit unknown

**Exactly-once is not claimed, because it cannot be honoured.** A claim found still
`EXECUTING` on a later attempt means the process died between step 2 and step 4. The
effect may or may not have happened, and no local information distinguishes the cases:

| Found status | Meaning | Action |
|---|---|---|
| `SUCCEEDED` | It happened | Return the stored result. Do not re-execute. |
| `FAILED` | It definitively did not | May retry |
| `EXECUTING` | **Unknown** | Mark `INDETERMINATE`. Do not re-execute, do not retry. |

`ActionStatus.INDETERMINATE` exists so that "we do not know" is representable. Collapsing
it into `FAILED` would make an unknown indistinguishable from a definite non-event, and
the next run would confidently duplicate a real email.

**An `INDETERMINATE` record requires human reconciliation.** No automatic recovery is
attempted, and none is built in Session 6.

### Retry

The executor retries `RATE_LIMITED` and `ADAPTER_ERROR` only, to a maximum of 3 attempts,
with deterministic doubling backoff and no jitter. It deliberately does **not** reuse
`ERROR_POLICY[...].retry`: that flag is *agent* guidance, and it marks `INVALID_ARGUMENTS`
retryable because an agent can fix its arguments. An executor's arguments come from a
persisted intervention, so re-sending them unchanged reproduces the identical failure.
Two different notions of "retryable", kept apart on purpose, with a test asserting the
executor's set is strictly narrower.

Every attempt writes its own `tool_calls` row, so retries are visible in the ledger
rather than hidden inside one.

## Alternatives considered

**Write the action record after the effect.** Rejected -- the failure mode above.

**Include `run_id` in the key.** Rejected: it makes every re-run a new effect, which is
the opposite of the guarantee.

**Re-execute on an `EXECUTING` row.** Rejected: it treats an ambiguous outcome as a
definite non-event and can produce the duplicate this design exists to prevent.

**Fail closed permanently on `EXECUTING`.** Rejected as too blunt for Session 6: a single
crash would wedge the action with no recovery path. `INDETERMINATE` records the ambiguity
without either guessing or deadlocking.

**A distributed lock or two-phase commit.** Rejected: no external system here supports
the second phase, and the guarantee would be theatre.

## Consequences

**Easier.** Resume, retry, and re-run are all safe by the same mechanism. `make demo`
proves it by executing the phase twice and showing zero new effects.

**Harder.** The system can produce an `INDETERMINATE` record that a human must resolve,
and there is no tooling for that yet.

**We now owe** a reconciliation path, and the discipline that anything added to the key's
definition bumps `KEY_VERSION` -- otherwise previously executed effects would silently
collide with newly computed ones on deploy day.

## Revisit when

1. **An adapter offers a server-side idempotency key** (Stripe-style). Then the remote
   system can deduplicate and `INDETERMINATE` becomes resolvable by querying it.
2. **An `INDETERMINATE` record actually occurs** outside a test, which is the signal that
   reconciliation tooling is owed rather than theoretical.
3. **Concurrent execution of the same incident** becomes possible, where the claim's
   commit boundary needs re-examining under real contention rather than argument.
