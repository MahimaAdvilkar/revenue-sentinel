"""Cost centre, evaluation history, and the integration catalogue.

All read-only, like everything else the dashboard consumes (ADR-0022).

Two of these carry a claim the code has to be careful about:

* **Cache effectiveness has never been measured.** The counters exist and are all zero,
  because no live API call has ever been made. Returning `0%` would read as "caching
  works badly"; this returns `observed: false` with a sentence saying why, and the UI
  renders that rather than a number.
* **Evaluation history is a list, not a status.** ADR-0021 made attempts append-only so a
  later pass cannot erase evidence of an earlier failure. An endpoint that returned only
  the latest result would undo that at the API layer, so this returns every attempt.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Final

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from revenue_sentinel.api.deps import get_session
from revenue_sentinel.api.schemas import (
    BudgetView,
    CostCentreResponse,
    EvaluationHistoryResponse,
    EvaluationRunSummary,
    IncidentCostView,
    IntegrationCatalogueResponse,
    IntegrationView,
    ModelMixEntry,
    ObservedMetric,
    RoadmapNoteView,
)
from revenue_sentinel.cost.pricing import cost_of
from revenue_sentinel.db.models import evaluation as eval_orm
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.db.models import workflow as workflow_orm
from revenue_sentinel.domain.enums import CostType
from revenue_sentinel.integrations.catalogue import catalogue
from revenue_sentinel.integrations.status import SIMULATED

router = APIRouter(tags=["centres"])

MICRO: Final = Decimal("0.000001")

CONCURRENCY_NOTE: Final = (
    "GLOBAL budget enforcement is not atomic across concurrent independent runs. "
    "Read-then-call is sound only because model calls are serialized within a run "
    "(ADR-0019)."
)


def _sum(session: Session, cost_type: CostType | None = None) -> Decimal:
    statement = sa.select(sa.func.coalesce(sa.func.sum(obs_orm.CostEntry.amount_usd), 0))
    if cost_type is not None:
        statement = statement.where(obs_orm.CostEntry.cost_type == cost_type)
    return Decimal(session.scalar(statement) or 0).quantize(MICRO)


@router.get("/cost", response_model=CostCentreResponse)
def cost_centre(session: Annotated[Session, Depends(get_session)]) -> CostCentreResponse:
    """Spend across every run, against every configured budget."""
    model_calls = int(
        session.scalar(sa.select(sa.func.count()).select_from(obs_orm.ModelCall)) or 0
    )
    tool_calls = int(session.scalar(sa.select(sa.func.count()).select_from(obs_orm.ToolCall)) or 0)

    versions = session.scalars(sa.select(obs_orm.CostEntry.pricing_version).distinct()).all()

    budgets = session.scalars(sa.select(obs_orm.Budget)).all()

    return CostCentreResponse(
        total_cost=str(_sum(session)),
        model_cost=str(_sum(session, CostType.MODEL_INFERENCE)),
        tool_cost=str(_sum(session, CostType.TOOL_INVOCATION)),
        model_calls=model_calls,
        tool_calls=tool_calls,
        pricing_versions=sorted(versions),
        budgets=[
            BudgetView(
                scope=budget.scope.value,
                scope_ref=budget.scope_ref,
                limit_usd=str(budget.limit_usd),
                consumed_usd=str(budget.consumed_usd),
                remaining_usd=str((budget.limit_usd - budget.consumed_usd).quantize(MICRO)),
                hard_stop=budget.hard_stop,
            )
            for budget in budgets
        ],
        by_incident=_by_incident(session),
        model_mix=_model_mix(session),
        cache_effectiveness=_cache_effectiveness(session),
        concurrency_note=CONCURRENCY_NOTE,
    )


def _by_incident(session: Session) -> list[IncidentCostView]:
    """Per-incident spend, split by cost type, ranked by total.

    Split properly rather than reported as a single figure with zeroed components: a
    column that always reads `0.000000` looks like a measurement of nothing spent, not
    like a field nobody filled in.
    """
    rows = session.execute(
        sa.select(
            workflow_orm.Incident.incident_ref,
            obs_orm.CostEntry.cost_type,
            sa.func.coalesce(sa.func.sum(obs_orm.CostEntry.amount_usd), 0),
            sa.func.count(obs_orm.CostEntry.id),
        )
        .join(
            workflow_orm.WorkflowRun,
            workflow_orm.WorkflowRun.incident_id == workflow_orm.Incident.id,
        )
        .join(obs_orm.CostEntry, obs_orm.CostEntry.run_id == workflow_orm.WorkflowRun.id)
        .group_by(workflow_orm.Incident.incident_ref, obs_orm.CostEntry.cost_type)
    ).all()

    totals: dict[str, dict[str, Decimal | int]] = {}
    for incident_ref, cost_type, amount, count in rows:
        bucket = totals.setdefault(
            str(incident_ref),
            {"model": Decimal(0), "tool": Decimal(0), "model_calls": 0, "tool_calls": 0},
        )
        key = "model" if cost_type is CostType.MODEL_INFERENCE else "tool"
        bucket[key] = Decimal(str(bucket[key])) + Decimal(amount or 0)
        bucket[f"{key}_calls"] = int(bucket[f"{key}_calls"]) + int(count)

    views = [
        IncidentCostView(
            incident_ref=incident_ref,
            model_cost=str(Decimal(str(bucket["model"])).quantize(MICRO)),
            tool_cost=str(Decimal(str(bucket["tool"])).quantize(MICRO)),
            total_cost=str(
                (Decimal(str(bucket["model"])) + Decimal(str(bucket["tool"]))).quantize(MICRO)
            ),
            model_calls=int(bucket["model_calls"]),
            tool_calls=int(bucket["tool_calls"]),
        )
        for incident_ref, bucket in totals.items()
    ]
    # Highest spend first, then by reference so the order is total rather than
    # dependent on dict iteration.
    return sorted(views, key=lambda view: (-Decimal(view.total_cost), view.incident_ref))


def _model_mix(session: Session) -> list[ModelMixEntry]:
    """Calls and cost per model.

    `replayed` is reported alongside `calls` because in v1 they are equal: every call is
    a fixture replay. A mix that did not say so would look like a routing measurement.
    """
    rows = session.execute(
        sa.select(
            obs_orm.ModelCall.model_id,
            sa.func.count(),
            sa.func.sum(sa.cast(obs_orm.ModelCall.is_replay, sa.Integer)),
            sa.func.coalesce(sa.func.sum(obs_orm.ModelCall.input_tokens), 0),
            sa.func.coalesce(sa.func.sum(obs_orm.ModelCall.output_tokens), 0),
        ).group_by(obs_orm.ModelCall.model_id)
    ).all()

    mix: list[ModelMixEntry] = []
    for model_id, calls, replayed, input_tokens, output_tokens in rows:
        # Priced from real token counts, which are zero in fixture mode. Nothing is
        # estimated here (ADR-0013).
        amount = cost_of(
            model_id=str(model_id),
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
        )
        mix.append(
            ModelMixEntry(
                model_id=str(model_id),
                calls=int(calls),
                cost_usd=str(amount),
                replayed=int(replayed or 0),
            )
        )
    return sorted(mix, key=lambda entry: entry.model_id)


def _cache_effectiveness(session: Session) -> ObservedMetric:
    """Never measured, and says so.

    Prompt caching is implemented in the pricing table and tested as arithmetic, but no
    cache hit has ever occurred because no live call has ever been made. Reporting `0%`
    would be a measurement claim this system cannot support.
    """
    reads = int(
        session.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(obs_orm.ModelCall.cache_read_tokens), 0))
        )
        or 0
    )
    writes = int(
        session.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(obs_orm.ModelCall.cache_write_tokens), 0))
        )
        or 0
    )

    if reads == 0 and writes == 0:
        return ObservedMetric(
            observed=False,
            value=None,
            note=(
                "Never observed. No live API call has been made, so no cache hit has "
                "ever occurred. This is an absence of data, not a hit rate of zero."
            ),
        )

    total = reads + writes
    rate = (Decimal(reads) / Decimal(total) * 100).quantize(Decimal("0.01"))
    return ObservedMetric(
        observed=True,
        value=f"{rate}%",
        note=f"{reads} cached input tokens read, {writes} written.",
    )


@router.get("/evaluation/runs", response_model=EvaluationHistoryResponse)
def evaluation_history(
    session: Annotated[Session, Depends(get_session)],
) -> EvaluationHistoryResponse:
    """Every evaluation attempt, most recently recorded first.

    **A failed attempt stays in this list**, and the list is never collapsed to a status.

    Ordered by `seq` -- the insertion sequence added in migration 0008 -- not by
    `started_at`. In fixture mode `started_at` is the frozen `EVALUATION_TIMESTAMP`, so
    every attempt of the golden run carries the same value and ordering by it is
    arbitrary between ties. `seq` is monotonic per insert, so this ordering is total and
    reproducible.
    """
    runs = session.scalars(
        sa.select(eval_orm.EvaluationRun).order_by(eval_orm.EvaluationRun.seq.desc())
    ).all()

    return EvaluationHistoryResponse(
        runs=[
            EvaluationRunSummary(
                evaluation_run_id=str(run.id),
                sequence=run.seq,
                suite_name=run.suite_name,
                evaluator_version=run.suite_version,
                started_at=run.started_at,
                passed=run.passed,
                total=run.total,
                outcome="passed" if run.passed == run.total else "failed",
            )
            for run in runs
        ],
        llm_judge_used=False,
        evaluation_cost="0.000000",
    )


@router.get("/integrations", response_model=IntegrationCatalogueResponse)
def integration_catalogue() -> IntegrationCatalogueResponse:
    """Every adapter, the status it declares, and the roadmap copy it wrote itself.

    Both come out of the adapter module (`integrations/catalogue.py`): the status through
    `status_of`, the same function the MCP server uses to stamp tool results, and the
    "what changes when this becomes real" text out of the module docstring. Nothing on
    this endpoint is written here. A catalogue that could disagree with the adapters would
    be worse than no catalogue.
    """
    entries = catalogue()

    return IntegrationCatalogueResponse(
        integrations=[
            IntegrationView(
                name=entry.name,
                module=entry.module,
                integration_status=entry.status,
                port=entry.port,
                summary=entry.summary,
                when_real=[
                    RoadmapNoteView(heading=note.heading, body=note.body)
                    for note in entry.when_real
                ],
                when_real_documented=entry.documented,
            )
            for entry in entries
        ],
        any_real=any(entry.status != SIMULATED for entry in entries),
    )
