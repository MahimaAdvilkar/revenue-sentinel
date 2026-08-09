"""Migration 0008: the evaluation history has a total, insertion-ordered sequence.

`evaluation_runs` is append-only (ADR-0021) so a later passing attempt cannot erase the
record of an earlier failure. That guarantee is only useful if the attempts can be put
back in order, and before `seq` they could not:

* `started_at` is **caller-supplied**, and in fixture mode it is the frozen
  `EVALUATION_TIMESTAMP` -- so every attempt of the golden run carries the same value.
* `created_at` defaults to `now()`, which in PostgreSQL is the **transaction** timestamp
  -- so attempts recorded in one transaction tie there too.
* `id` is a UUID4. Ordering by it is stable but unrelated to when anything happened.

Each of those is asserted below rather than described, because "the timestamps tie" is
exactly the kind of claim that is true until someone changes a default.

The sequence is **global**, not scoped per suite or per workflow run. The history endpoint
returns every attempt across every suite in one list, so a per-suite counter would have to
be re-derived at read time to order that list -- and would answer a question ("the third
attempt of this suite") that no screen asks.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from revenue_sentinel.core.config import PROJECT_ROOT, Settings
from revenue_sentinel.core.ids import new_id
from revenue_sentinel.db.models import evaluation as eval_orm


def _attempt(
    session: Session, *, started_at: datetime, passed: int, total: int
) -> eval_orm.EvaluationRun:
    run = eval_orm.EvaluationRun(
        id=new_id(),
        suite_name="ordering-probe",
        suite_version="evaluator/v1",
        started_at=started_at,
        passed=passed,
        total=total,
    )
    session.add(run)
    session.flush()
    return run


def test_started_at_ties_for_attempts_of_the_golden_run(
    seeded_session: Session, settings: Settings
) -> None:
    """The reason `seq` exists. Ordering by a frozen timestamp is arbitrary."""
    for _ in range(3):
        _attempt(seeded_session, started_at=settings.evaluation_timestamp, passed=6, total=6)

    started = seeded_session.scalars(
        sa.select(eval_orm.EvaluationRun.started_at).where(
            eval_orm.EvaluationRun.suite_name == "ordering-probe"
        )
    ).all()

    assert len(started) == 3
    assert len(set(started)) == 1, "the tie the sequence exists to break"


def test_created_at_ties_within_one_transaction(
    seeded_session: Session, settings: Settings
) -> None:
    """`now()` is the transaction timestamp in PostgreSQL, not the statement timestamp.

    So `created_at` cannot order attempts written by a single evaluation batch either.
    """
    for _ in range(3):
        _attempt(seeded_session, started_at=settings.evaluation_timestamp, passed=6, total=6)

    created = seeded_session.scalars(
        sa.select(eval_orm.EvaluationRun.created_at).where(
            eval_orm.EvaluationRun.suite_name == "ordering-probe"
        )
    ).all()

    assert len(set(created)) == 1, "created_at ties inside a transaction"


def test_seq_is_unique_monotonic_and_matches_insertion_order(
    seeded_session: Session, settings: Settings
) -> None:
    runs = [
        _attempt(seeded_session, started_at=settings.evaluation_timestamp, passed=n, total=6)
        for n in (4, 6, 5)
    ]

    sequences = [run.seq for run in runs]

    assert len(set(sequences)) == 3
    assert sequences == sorted(sequences), "insertion order, not value order"
    # `passed` descends then rises across the three attempts, so a sequence that tracked
    # any property of the row rather than the insert would not come out sorted.
    assert [run.passed for run in runs] == [4, 6, 5]


def test_ordering_by_seq_keeps_a_failure_visible_after_a_later_pass(
    seeded_session: Session, settings: Settings
) -> None:
    """The behaviour the ordering is *for*, asserted at the query the endpoint runs."""
    failed = _attempt(seeded_session, started_at=settings.evaluation_timestamp, passed=4, total=6)
    passed = _attempt(seeded_session, started_at=settings.evaluation_timestamp, passed=6, total=6)

    history = seeded_session.scalars(
        sa.select(eval_orm.EvaluationRun)
        .where(eval_orm.EvaluationRun.suite_name == "ordering-probe")
        .order_by(eval_orm.EvaluationRun.seq.desc())
    ).all()

    assert [run.id for run in history] == [passed.id, failed.id]
    assert any(run.passed < run.total for run in history), "the failure survived the pass"


def test_the_order_is_the_same_on_every_read(seeded_session: Session, settings: Settings) -> None:
    """A tie broken arbitrarily can come back differently. A total order cannot."""
    for passed in (4, 6, 5, 6):
        _attempt(seeded_session, started_at=settings.evaluation_timestamp, passed=passed, total=6)

    def read() -> list[int]:
        return list(
            seeded_session.scalars(
                sa.select(eval_orm.EvaluationRun.seq)
                .where(eval_orm.EvaluationRun.suite_name == "ordering-probe")
                .order_by(eval_orm.EvaluationRun.seq.desc())
            ).all()
        )

    assert read() == read() == read()


def test_seq_cannot_be_written_by_the_application(
    seeded_session: Session, settings: Settings
) -> None:
    """`IDENTITY ALWAYS`, so nothing can renumber the history -- not even by accident.

    An append-only log whose ordering key is writable is an append-only log with an
    editable order.
    """
    run = eval_orm.EvaluationRun(
        id=new_id(),
        seq=999_999,
        suite_name="ordering-probe",
        suite_version="evaluator/v1",
        started_at=settings.evaluation_timestamp,
        passed=6,
        total=6,
    )
    seeded_session.add(run)

    with pytest.raises(sa.exc.DatabaseError):
        seeded_session.flush()
    seeded_session.rollback()


def _alembic(command: list[str], url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell, no user input
        [sys.executable, "-m", "alembic", *command],
        cwd=PROJECT_ROOT,
        env={**os.environ, "ALEMBIC_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )


def test_0008_downgrades_and_re_upgrades_with_rows_present(
    migrated_database_url: str, engine: Engine
) -> None:
    """Down and back up on data, because that is how a real rollback happens.

    Postgres backfills an identity column in physical order when it is added, which is the
    best available reconstruction for rows that predate it -- approximate for those,
    exact for everything recorded afterwards. This asserts the round trip survives rows
    rather than only surviving an empty schema.
    """
    with Session(engine) as session:
        for passed in (4, 6):
            session.add(
                eval_orm.EvaluationRun(
                    id=new_id(),
                    suite_name="rollback-probe",
                    suite_version="evaluator/v1",
                    started_at=datetime.fromisoformat("2026-08-01T12:00:00+00:00"),
                    passed=passed,
                    total=6,
                )
            )
        session.commit()

    down = _alembic(["downgrade", "0007"], migrated_database_url)
    assert down.returncode == 0, down.stderr

    with engine.connect() as connection:
        columns = {column["name"] for column in sa.inspect(engine).get_columns("evaluation_runs")}
        assert "seq" not in columns
        # The attempts themselves survive the downgrade: only the ordering key is dropped.
        remaining = connection.execute(
            sa.text("SELECT count(*) FROM evaluation_runs WHERE suite_name = 'rollback-probe'")
        ).scalar()
        assert remaining == 2

    up = _alembic(["upgrade", "head"], migrated_database_url)
    assert up.returncode == 0, up.stderr

    with Session(engine) as session:
        restored = session.scalars(
            sa.select(eval_orm.EvaluationRun.seq)
            .where(eval_orm.EvaluationRun.suite_name == "rollback-probe")
            .order_by(eval_orm.EvaluationRun.seq)
        ).all()
        assert len(set(restored)) == 2, "every row was renumbered uniquely"

        session.execute(
            sa.delete(eval_orm.EvaluationRun).where(
                eval_orm.EvaluationRun.suite_name == "rollback-probe"
            )
        )
        session.commit()
