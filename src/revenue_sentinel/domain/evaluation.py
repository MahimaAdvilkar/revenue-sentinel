"""Evaluation suite results.

`expected` and `actual` are stored as text on purpose: a rubric check compares
heterogeneous things -- a count, a decision, a dollar figure -- and the value of the
record is that a human can read why a check failed without re-running it.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from revenue_sentinel.domain.base import DomainModel, NonEmptyStr, UtcDatetime
from revenue_sentinel.domain.enums import EvaluationOutcome


class EvaluationRun(DomainModel):
    """One execution of a named rubric suite."""

    id: UUID
    suite_name: NonEmptyStr
    suite_version: NonEmptyStr
    started_at: UtcDatetime
    ended_at: UtcDatetime | None = None
    passed: int = Field(ge=0)
    total: int = Field(ge=0)

    @model_validator(mode="after")
    def _passed_within_total(self) -> EvaluationRun:
        if self.passed > self.total:
            raise ValueError("passed exceeds total")
        return self


class EvaluationResult(DomainModel):
    """One check within a suite run."""

    id: UUID
    evaluation_run_id: UUID
    workflow_run_id: UUID | None = None
    check_name: NonEmptyStr
    outcome: EvaluationOutcome
    expected: str
    actual: str
    detail: str | None = None
