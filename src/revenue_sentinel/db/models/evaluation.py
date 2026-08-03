"""Evaluation suite tables."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from revenue_sentinel.db.base import (
    Base,
    CreatedAtMixin,
    long_text,
    pg_enum,
    short_text,
    timestamp_tz,
    uuid_fk,
    uuid_pk,
)
from revenue_sentinel.domain.enums import EvaluationOutcome


class EvaluationRun(Base, CreatedAtMixin):
    __tablename__ = "evaluation_runs"

    id: Mapped[uuid_pk]
    suite_name: Mapped[short_text]
    suite_version: Mapped[str] = mapped_column(sa.String(32))
    started_at: Mapped[timestamp_tz]
    ended_at: Mapped[timestamp_tz | None] = mapped_column(nullable=True)
    passed: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("0"))
    total: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("0"))

    __table_args__ = (
        sa.CheckConstraint(
            "passed >= 0 AND total >= 0 AND passed <= total", name="counts_coherent"
        ),
    )


class EvaluationResult(Base, CreatedAtMixin):
    __tablename__ = "evaluation_results"

    id: Mapped[uuid_pk]
    evaluation_run_id: Mapped[uuid_fk] = mapped_column(
        sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE")
    )
    workflow_run_id: Mapped[uuid_fk | None] = mapped_column(
        sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    check_name: Mapped[short_text]
    outcome: Mapped[EvaluationOutcome] = mapped_column(
        pg_enum(EvaluationOutcome, "evaluation_outcome")
    )
    expected: Mapped[long_text]
    actual: Mapped[long_text]
    detail: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint(
            "evaluation_run_id", "check_name", name="uq_evaluation_results_run_id_check_name"
        ),
        sa.Index("ix_evaluation_results_outcome", "outcome"),
    )
