# ADR-0025: `INDETERMINATE` actions are reconciled by an attested human, not by the system

**Status:** Accepted
**Date:** 2026-08-09
**Deciders:** Mahima Advilkar

## Context

ADR-0017 made execution at-least-once with an explicit unknown. An `action_records` row
claimed as `EXECUTING` and found still `EXECUTING` on a later attempt means the process
died between claiming the effect and recording its outcome. The effect may or may not have
happened. Retrying could send a second email; marking it failed could hide one that was
sent. Neither guess is worth making silently, so the row becomes `INDETERMINATE`.

That was the right decision and it left a hole: **there was no way to act on it.** The
state was reachable, correct, and inert. `ActionStatus.INDETERMINATE` existed, the executor
set it, a test proved it, and no command, endpoint, or screen let anyone resolve one. A
state that means "a person must decide" with no affordance for that person is a state that
will accumulate silently in production and be discovered during an incident.

This is the largest honest gap the project carried into its final milestone, and it is the
one most worth closing, because the alternative implementations are all subtly wrong in
ways that are easy to ship and hard to detect.

## Decision

**Reconciliation is a recorded human attestation, and the system supplies no opinion.**

Concretely:

**1. Two terminal outcomes, and no third.** `INDETERMINATE` resolves to `SUCCEEDED` (the
operator found evidence the effect occurred) or `FAILED` (the operator found evidence it
did not). There is deliberately **no "resolved, still unknown"** state. Such a state would
be a way to close a ticket without answering the question, and the whole point of
`INDETERMINATE` is that the question must be answered by someone accountable.

**2. Evidence is mandatory.** `rs reconcile` refuses an empty or whitespace-only
`--evidence`. The text is free-form and the system cannot verify it -- there is no external
system to check against, and there will not be one in v1. What the system *can* do is
require it, attribute it, timestamp it, and keep it forever. An attestation without a
stated basis is an opinion; with one it is a record a later reader can judge.

**3. The actor is required and claimed, not authenticated.** `--as` carries the same
meaning it carries for approvals (ADR-0018): a claimed identity, not a verified one. The
reconciliation record says who *said* they checked. Nothing here authenticates them, and
the CLI output says so.

**4. There is no retry-anyway control.** A retry is reachable only *after* an operator has
attested `did-not-occur`, which is exactly the point: retrying becomes a consequence of a
human assertion that no effect exists, rather than a button someone presses when they are
in a hurry. A "retry anyway" affordance on an uncertain action is the single most dangerous
control this system could offer, because it looks helpful and its failure mode is a
duplicate real-world side effect.

**5. The idempotency key is never released.** Reconciling to `FAILED` does not free the
key, delete the row, or relax the `UNIQUE` constraint. A subsequent attempt claims the same
key with an incremented `attempt_count`, exactly as before. Reconciliation changes what we
*know* about an effect; it changes nothing about how effects are identified.

**6. Reconciliation is append-only in the audit trail.** An `action.reconciled` audit event
records the prior status, the new status, the actor, the evidence, and the time. The
`action_records` row also carries `reconciled_by`, `reconciled_at`, and
`reconciliation_evidence` (migration 0009) so the attestation is visible on the row itself
rather than only reconstructable by replaying events. Both, deliberately: the event is the
history, the columns are the answer to "who resolved this, and on what basis".

**7. Reconciling an already-reconciled action is refused.** The transition is
`INDETERMINATE -> {SUCCEEDED, FAILED}` and nothing else. A second reconciliation would
overwrite an attestation, which would make the record editable and therefore worthless.

**8. CLI first; the dashboard stays read-only.** Three commands -- `rs actions
--status indeterminate`, `rs action <ref>`, `rs reconcile <ref> ...`. The dashboard gains a
panel that *lists* uncertain actions and renders the exact command, with no button, form,
or input. This is the same shape as the approval inbox and for the same reason (ADR-0022):
there is no authenticated identity, so a browser control would imply an accountable user
who does not exist.

**9. Exactly-once is still not claimed, anywhere.** Reconciliation converts an unknown into
a human-attested known. It does not make delivery exactly-once, and the CLI output, the
dashboard panel, and this record all say at-least-once in those words.

## Alternatives considered

**Automatic retry with a bounded attempt count.** Rejected -- this is the failure ADR-0017
exists to prevent. The attempt count says nothing about whether the effect occurred.

**Automatic resolution by querying the external system.** Rejected as unavailable and, more
importantly, as not obviously correct even when available: "no draft with this subject
exists now" does not prove none was created and deleted, and treating a provider read as
proof would launder an inference into a fact. When real integrations land, a provider query
should *inform the operator's evidence*, not replace the attestation.

**A third `RESOLVED_UNKNOWN` state.** Rejected. It reads as diligence and functions as a
way to stop looking. If an operator genuinely cannot determine the outcome, the correct
state is the one the row already holds.

**Timeout-based auto-resolution to `FAILED`.** Rejected outright: it converts "we do not
know" into "it did not happen" on the basis of elapsed time, which is a guess wearing a
policy's clothes, and it hides exactly the effects most worth finding.

**An HTTP endpoint plus a dashboard button.** Rejected for v1 under ADR-0022. It is the
right shape once authenticated identity exists, and it would be dishonest before then.

**Reconciliation as an audit event only, with no columns on the row.** Rejected: answering
"is this resolved, and by whom" would require replaying the event log, so the common query
would be the expensive one and any read path that forgot to replay would show a resolved
action as still uncertain.

## Consequences

**Easier.** An operator can find every uncertain action, see exactly what was attempted and
what authorised it, and record a decision that survives. The state stops being inert.

**Harder.** Reconciliation now needs a person, and the system will not do it for them.
That is the intended cost. At production volume this becomes a real operational burden and
the honest answer is that the burden is a property of at-least-once delivery, not of this
design -- the alternative is not less work, it is undetected duplicates.

**We now owe** a reconciliation path in any future execution surface. If a second executor
is ever added, it inherits `INDETERMINATE`, and shipping it without a reconciliation route
would recreate this gap somewhere new.

## Revisit when

1. **Real integrations land.** A provider query (Gmail message id, CRM task id) should be
   offered to the operator as *supporting evidence to paste*, and the evidence field should
   gain optional structure -- but the attestation stays human.
2. **Authenticated identity exists.** The dashboard panel should become an authenticated
   mutation at that point, and this decision's CLI-only constraint is what should be
   reopened -- not the attestation requirement.
3. **The volume of `INDETERMINATE` rows exceeds what a person can review**, which is the
   signal that the executor's crash window is too wide and the fix belongs upstream in
   execution, not downstream in reconciliation.
