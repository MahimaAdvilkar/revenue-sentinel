"""Performing an authorised effect, exactly once if the world cooperates.

The ordering below is the whole design, and it is worth stating plainly because the
obvious alternative is wrong:

1. Authorise (`authorization.py`), which re-evaluates policy and checks approval.
2. **Claim the idempotency key** by inserting an `action_records` row as `EXECUTING`,
   and commit that claim.
3. Perform the effect through `mcp/`.
4. Record the outcome.

Writing the record *after* the effect is the classic bug: crash between 3 and 4 and the
next run happily sends a second email. Claiming first means the row is the lock, and the
`UNIQUE` constraint on `idempotency_key` is what makes the lock real rather than advisory.

**This is at-least-once with an explicit unknown, not exactly-once** (ADR-0017). A claim
found still `EXECUTING` on a later attempt means the process died mid-effect: it may or
may not have happened. Retrying could duplicate a real email; marking it failed could
hide one. It is recorded as `INDETERMINATE` for a human, because neither guess is worth
making silently.

Every result carries `integration_status: "SIMULATED"` from the adapter through the
envelope to the printed line. Nothing here can execute against a real system, and nothing
here pretends otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from revenue_sentinel.core.ids import new_id
from revenue_sentinel.core.logging import get_logger
from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.db.models import governance as gov_orm
from revenue_sentinel.domain.enums import ActionStatus, ActionType
from revenue_sentinel.execution.authorization import ExecutionGrant
from revenue_sentinel.execution.idempotency import idempotency_key
from revenue_sentinel.execution.retry import (
    MAX_ATTEMPTS,
    SleepFn,
    backoff_ms,
    is_retryable,
    no_sleep,
)
from revenue_sentinel.mcp.client import McpClient
from revenue_sentinel.mcp.errors import ToolErrorCode

logger = get_logger(__name__)

TOOL_FOR_ACTION: dict[ActionType, str] = {
    ActionType.CRM_TASK: "crm_create_task",
    ActionType.EMAIL_DRAFT: "messaging_create_email_draft",
    ActionType.SLACK_APPROVAL_REQUEST: "messaging_send_slack_approval",
}
"""`CRM_FIELD_UPDATE` is deliberately absent. `crm_update_opportunity` remains
unreachable in v1: it is registered, policy-classified, and tested, but nothing routes to
it. An action type with no tool here cannot execute, which is a cheaper guarantee than
one enforced by a conditional somewhere."""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """What one attempt to perform an effect produced."""

    action_record_id: UUID
    status: ActionStatus
    attempts: int
    payload: JSONObject
    already_done: bool
    """`True` when the effect had already been performed and nothing new happened. This
    is what makes a re-run provably a no-op rather than merely a quiet one."""


class UnroutableActionError(RuntimeError):
    """An authorised action type with no tool behind it."""


def execute(
    session: Session,
    grant: ExecutionGrant,
    *,
    client: McpClient,
    incident_ref: str,
    run_id: UUID,
    arguments: JSONObject,
    occurred_at: datetime,
    sleep: SleepFn = no_sleep,
) -> ExecutionResult:
    """Perform one authorised effect, or return the one already performed."""
    tool_name = TOOL_FOR_ACTION.get(grant.action_type)
    if tool_name is None:
        raise UnroutableActionError(
            f"{grant.action_type.value} has no tool bound. It is not executable in v1."
        )

    key = idempotency_key(
        incident_ref=incident_ref,
        action_type=grant.action_type,
        target_ref=grant.target_ref,
        arguments=arguments,
    )

    claimed, record = _claim(session, grant, key=key, run_id=run_id, occurred_at=occurred_at)
    if not claimed:
        return _resolve_existing(session, record, occurred_at=occurred_at)

    return _perform(
        session,
        record,
        client=client,
        tool_name=tool_name,
        arguments=arguments,
        occurred_at=occurred_at,
        sleep=sleep,
    )


def _claim(
    session: Session,
    grant: ExecutionGrant,
    *,
    key: str,
    run_id: UUID,
    occurred_at: datetime,
) -> tuple[bool, gov_orm.ActionRecord]:
    """Insert the claim, or discover that someone already owns this effect.

    `ON CONFLICT DO NOTHING` rather than a `SELECT` then `INSERT`: the check-then-act
    version has a race that a `UNIQUE` constraint would turn into an integrity error at
    the worst possible moment.
    """
    statement = (
        pg_insert(gov_orm.ActionRecord)
        .values(
            id=new_id(),
            run_id=run_id,
            intervention_id=grant.intervention_id,
            action_type=grant.action_type,
            idempotency_key=key,
            status=ActionStatus.EXECUTING,
            authorized_by=grant.policy_evaluation_id,
            approval_request_id=grant.approval_request_id,
            attempt_count=0,
            result=None,
            executed_at=None,
            target_ref=grant.target_ref,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(gov_orm.ActionRecord.id)
    )
    inserted = session.execute(statement).scalar_one_or_none()
    session.flush()

    existing = session.scalar(
        sa.select(gov_orm.ActionRecord).where(gov_orm.ActionRecord.idempotency_key == key)
    )
    if existing is None:  # pragma: no cover -- the insert either succeeded or conflicted
        raise RuntimeError(f"action record for {key} vanished between insert and read")

    return inserted is not None, existing


def _resolve_existing(
    session: Session, record: gov_orm.ActionRecord, *, occurred_at: datetime
) -> ExecutionResult:
    """Someone already owns this effect. Decide what that means without guessing."""
    if record.status is ActionStatus.SUCCEEDED:
        return ExecutionResult(
            action_record_id=record.id,
            status=record.status,
            attempts=record.attempt_count,
            payload=record.result or {},
            already_done=True,
        )

    if record.status is ActionStatus.EXECUTING:
        # Claimed but never resolved: the process died between claiming and recording.
        # The effect may or may not have happened, and neither answer is safe to assume.
        record.status = ActionStatus.INDETERMINATE
        session.flush()
        logger.warning(
            "action_indeterminate",
            action_record_id=str(record.id),
            idempotency_key=record.idempotency_key,
            detail="claimed but unresolved; requires reconciliation (ADR-0017)",
        )

    return ExecutionResult(
        action_record_id=record.id,
        status=record.status,
        attempts=record.attempt_count,
        payload=record.result or {},
        already_done=True,
    )


def _perform(
    session: Session,
    record: gov_orm.ActionRecord,
    *,
    client: McpClient,
    tool_name: str,
    arguments: JSONObject,
    occurred_at: datetime,
    sleep: SleepFn,
) -> ExecutionResult:
    """Call the tool, retrying only genuinely transient failures."""
    payload: JSONObject = {}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        record.attempt_count = attempt
        session.flush()

        payload = client.call_tool(tool_name, arguments)
        if payload.get("ok") is True:
            record.status = ActionStatus.SUCCEEDED
            record.result = payload
            record.executed_at = occurred_at
            session.flush()
            return ExecutionResult(
                action_record_id=record.id,
                status=record.status,
                attempts=attempt,
                payload=payload,
                already_done=False,
            )

        code = _error_code(payload)
        if code is None or not is_retryable(code) or attempt == MAX_ATTEMPTS:
            record.status = ActionStatus.FAILED
            record.result = payload
            session.flush()
            return ExecutionResult(
                action_record_id=record.id,
                status=record.status,
                attempts=attempt,
                payload=payload,
                already_done=False,
            )

        sleep(backoff_ms(attempt) / 1000)

    raise RuntimeError("unreachable: the loop returns on every path")  # pragma: no cover


def _error_code(payload: JSONObject) -> ToolErrorCode | None:
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    if not isinstance(code, str):
        return None
    try:
        return ToolErrorCode(code)
    except ValueError:
        return None
