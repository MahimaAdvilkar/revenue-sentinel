"""Resolving an `INDETERMINATE` action -- by a person, on stated evidence (ADR-0025).

An action claimed as `EXECUTING` and found still `EXECUTING` on a later attempt means the
process died between claiming the effect and recording its outcome. The effect may or may
not have happened. ADR-0017 records that as `INDETERMINATE` rather than guessing; this
module is how a human ends the uncertainty.

Four rules, each of which exists because the obvious alternative is dangerous:

* **Only `INDETERMINATE` reconciles**, and only to `SUCCEEDED` or `FAILED`. There is no
  "resolved but still unknown" -- that would be a way to close the question without
  answering it.
* **Evidence is mandatory.** This system cannot verify what an operator saw in an external
  system, and will not pretend to. What it can do is require a stated basis, attribute it,
  and keep it. An attestation without a basis is an opinion.
* **Nothing retries here.** A retry becomes reachable only after somebody attests
  `did-not-occur`. A "retry anyway" control on an uncertain action is the most dangerous
  affordance this system could offer: it looks helpful, and its failure mode is a
  duplicated real-world effect.
* **The idempotency key is never released.** Reconciling to `FAILED` does not free the key
  or relax the UNIQUE constraint. Reconciliation changes what we *know* about an effect,
  never how effects are identified.

**This does not make delivery exactly-once.** It converts an unknown into a human-attested
known. Execution remains at-least-once (ADR-0017), and every message this module produces
says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.ids import new_id
from revenue_sentinel.core.logging import get_logger
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.domain.enums import ActionStatus

logger = get_logger(__name__)

RECONCILED_EVENT: Final = "action.reconciled"

DELIVERY_CAVEAT: Final = (
    "Execution is at-least-once with an explicit unknown (ADR-0017). Reconciliation "
    "records what a person attests happened; it does not make delivery exactly-once."
)


class Outcome(StrEnum):
    """What the operator says they found. Nothing else is accepted."""

    OCCURRED = "occurred"
    DID_NOT_OCCUR = "did-not-occur"

    @property
    def status(self) -> ActionStatus:
        return ActionStatus.SUCCEEDED if self is Outcome.OCCURRED else ActionStatus.FAILED


class ReconciliationError(RuntimeError):
    """A reconciliation was refused. The message is written for an operator to read."""


@dataclass(frozen=True, slots=True)
class UncertainAction:
    """One action awaiting a human decision, with what an operator needs to check it."""

    action_record_id: UUID
    incident_ref: str
    action_type: str
    target_ref: str
    idempotency_key: str
    attempt_count: int
    claimed_at: datetime | None
    integration_status: str
    reconcile_command: str


def _reconcile_command(action_record_id: UUID) -> str:
    """The exact command an operator runs. Rendered, never executed for them."""
    return (
        f"uv run rs reconcile {action_record_id} "
        f"--outcome occurred|did-not-occur --as usr:your-name --evidence '<what you saw>'"
    )


def list_uncertain(session: Session) -> list[UncertainAction]:
    """Every unresolved `INDETERMINATE` action, oldest claim first.

    Oldest first because these are a queue of work, and the one that has been uncertain
    longest is the one most likely to have been forgotten.
    """
    rows = session.execute(
        sa.select(gov_orm.ActionRecord, workflow_orm.Incident.incident_ref)
        .join(workflow_orm.WorkflowRun, workflow_orm.WorkflowRun.id == gov_orm.ActionRecord.run_id)
        .join(
            workflow_orm.Incident, workflow_orm.Incident.id == workflow_orm.WorkflowRun.incident_id
        )
        .where(
            gov_orm.ActionRecord.status == ActionStatus.INDETERMINATE,
            gov_orm.ActionRecord.reconciled_by.is_(None),
        )
        .order_by(gov_orm.ActionRecord.created_at)
    ).all()

    return [
        UncertainAction(
            action_record_id=record.id,
            incident_ref=str(incident_ref),
            action_type=record.action_type.value,
            target_ref=record.target_ref,
            idempotency_key=record.idempotency_key,
            attempt_count=record.attempt_count,
            claimed_at=record.created_at,
            # Every adapter in v1 is fixture-backed, so nothing here ever touched a real
            # system. Stated per row rather than assumed by the reader (rule 5).
            integration_status="SIMULATED",
            reconcile_command=_reconcile_command(record.id),
        )
        for record, incident_ref in rows
    ]


def get_action(session: Session, action_record_id: UUID) -> gov_orm.ActionRecord:
    record = session.get(gov_orm.ActionRecord, action_record_id)
    if record is None:
        raise ReconciliationError(f"no action record {action_record_id}")
    return record


def reconcile(
    session: Session,
    *,
    action_record_id: UUID,
    outcome: Outcome,
    actor: str,
    evidence: str,
    occurred_at: datetime,
) -> gov_orm.ActionRecord:
    """Record a human's finding about an uncertain action.

    Refuses rather than coerces: a non-`INDETERMINATE` action, a blank actor, blank
    evidence, or a second reconciliation all raise. Each refusal names what to do instead,
    because the person reading it is mid-incident.
    """
    record = get_action(session, action_record_id)

    if record.reconciled_by is not None:
        raise ReconciliationError(
            f"action {action_record_id} was already reconciled by {record.reconciled_by} "
            f"at {record.reconciled_at:%Y-%m-%dT%H:%M:%S%z} and is now "
            f"{record.status.value}. An attestation is a record, not a draft -- it is "
            f"never overwritten."
        )

    if record.status is not ActionStatus.INDETERMINATE:
        raise ReconciliationError(
            f"action {action_record_id} is {record.status.value}, not indeterminate. "
            f"Only an action whose outcome is genuinely unknown can be reconciled; "
            f"there is nothing here for a person to decide."
        )

    if not actor.strip():
        raise ReconciliationError(
            "--as is required. The attestation records who says they checked, and an "
            "unattributed one is worth nothing."
        )

    if not evidence.strip():
        raise ReconciliationError(
            "--evidence is required and must not be blank. State what you observed in "
            "the external system -- a message id, a CRM task URL, or the search you ran "
            "and found nothing. This system cannot verify it; it can require that you "
            "said it."
        )

    previous = record.status
    record.status = outcome.status
    record.reconciled_by = actor.strip()
    record.reconciled_at = occurred_at
    record.reconciliation_evidence = evidence.strip()
    session.flush()

    # Append-only. The row now answers "is this resolved"; this answers "what happened,
    # in order" -- and it is never updated or deleted.
    session.add(
        obs_orm.AuditEvent(
            id=new_id(),
            run_id=record.run_id,
            incident_id=session.scalar(
                sa.select(workflow_orm.WorkflowRun.incident_id).where(
                    workflow_orm.WorkflowRun.id == record.run_id
                )
            ),
            event_type=RECONCILED_EVENT,
            actor=actor.strip(),
            payload={
                "action_record_id": str(record.id),
                "previous_status": previous.value,
                "new_status": record.status.value,
                "outcome": outcome.value,
                "evidence": evidence.strip(),
                # Preserved so the event alone proves the key was not recycled.
                "idempotency_key": record.idempotency_key,
                "attempt_count": record.attempt_count,
                "identity": "claimed, not authenticated (ADR-0018)",
                "delivery": DELIVERY_CAVEAT,
            },
            occurred_at=occurred_at,
        )
    )
    session.flush()

    logger.info(
        "action_reconciled",
        action_record_id=str(record.id),
        previous_status=previous.value,
        new_status=record.status.value,
        actor=actor.strip(),
    )
    return record
