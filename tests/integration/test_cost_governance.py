"""Budgets, ceilings, and the ledger -- enforced before the spend.

The golden run costs **$0.00**, and that is the honest figure: fixture mode consumes no
tokens. So these tests prove enforcement by configuring budgets whose limits the
*worst-case reservation* would breach, rather than by inventing token counts.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.core.ids import new_id
from revenue_sentinel.cost import ledger as cost_ledger
from revenue_sentinel.cost.governor import (
    MAX_MODEL_CALLS_PER_RUN,
    MAX_TOOL_CALLS_PER_RUN,
    CostGovernor,
)
from revenue_sentinel.cost.pricing import PRICING_VERSION, worst_case_cost
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import BudgetPeriod, BudgetScope, CostType, PolicyDecision
from revenue_sentinel.mcp.errors import ToolErrorCode, ToolFailureError
from revenue_sentinel.orchestration import runner

INCIDENT = "INC-001"


def make_budget(
    session: Session,
    *,
    scope: BudgetScope,
    scope_ref: str | None,
    limit: str,
    consumed: str = "0",
    hard_stop: bool = True,
) -> obs_orm.Budget:
    budget = obs_orm.Budget(
        id=new_id(),
        scope=scope,
        scope_ref=scope_ref,
        period=BudgetPeriod.MONTHLY if scope is BudgetScope.GLOBAL else BudgetPeriod.RUN,
        limit_usd=Decimal(limit),
        consumed_usd=Decimal(consumed),
        hard_stop=hard_stop,
    )
    session.add(budget)
    session.flush()
    return budget


def governor(session: Session, run_id: UUID) -> CostGovernor:
    return CostGovernor(session, run_id=run_id, incident_ref=INCIDENT)


# ---------------------------------------------------------------------------
# The ledger records every call, including free ones
# ---------------------------------------------------------------------------
def test_every_model_call_writes_a_cost_entry(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    entries = detected.scalars(
        sa.select(obs_orm.CostEntry).where(
            obs_orm.CostEntry.run_id == investigated.run_id,
            obs_orm.CostEntry.cost_type == CostType.MODEL_INFERENCE,
        )
    ).all()

    model_calls = detected.scalar(
        sa.select(sa.func.count())
        .select_from(obs_orm.ModelCall)
        .where(obs_orm.ModelCall.run_id == investigated.run_id)
    )

    assert len(entries) == model_calls
    assert all(entry.pricing_version == PRICING_VERSION for entry in entries)


def test_fixture_mode_costs_exactly_zero_and_says_so(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """Not an estimate and not a placeholder -- zero tokens were consumed."""
    total = cost_ledger.run_total(detected, investigated.run_id)

    assert total == Decimal("0.000000")
    replayed = detected.scalars(
        sa.select(obs_orm.ModelCall).where(obs_orm.ModelCall.run_id == investigated.run_id)
    ).all()
    assert all(call.is_replay for call in replayed)
    assert all(call.input_tokens == 0 and call.output_tokens == 0 for call in replayed)


def test_free_tool_calls_still_get_an_entry(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """An absent row would be ambiguous between "free" and "not recorded"."""
    tool_entries = detected.scalars(
        sa.select(obs_orm.CostEntry).where(
            obs_orm.CostEntry.run_id == investigated.run_id,
            obs_orm.CostEntry.cost_type == CostType.TOOL_INVOCATION,
        )
    ).all()

    assert tool_entries
    assert all(entry.amount_usd == Decimal("0.000000") for entry in tool_entries)


def test_the_ledger_reconciles_with_consumed_budget(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """`SUM(cost_entries) == budgets.consumed_usd`, exactly."""
    make_budget(detected, scope=BudgetScope.RUN, scope_ref=str(investigated.run_id), limit="1.00")
    call = obs_orm.ModelCall(
        id=new_id(),
        run_id=investigated.run_id,
        node_name="probe",
        model_id="claude-opus-5",
        effort="high",
        input_tokens=1_000,
        output_tokens=1_000,
        cache_read_tokens=0,
        cache_write_tokens=0,
        latency_ms=1,
        stop_reason="end_turn",
        is_replay=False,
        trace_id="a" * 32,
        span_id="b" * 16,
    )
    detected.add(call)
    detected.flush()

    entry = cost_ledger.record_model_cost(
        detected,
        run_id=investigated.run_id,
        model_call=call,
        occurred_at=investigated.state.evaluated_at,
    )

    budget = detected.scalar(
        sa.select(obs_orm.Budget).where(obs_orm.Budget.scope_ref == str(investigated.run_id))
    )
    assert budget is not None
    assert entry.amount_usd == Decimal("0.030000")
    assert budget.consumed_usd == entry.amount_usd
    assert cost_ledger.run_total(detected, investigated.run_id) == entry.amount_usd


# ---------------------------------------------------------------------------
# Pre-spend enforcement (ADR-0019)
# ---------------------------------------------------------------------------
def test_a_reservation_that_would_breach_is_refused_before_spending(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    make_budget(detected, scope=BudgetScope.RUN, scope_ref=str(investigated.run_id), limit="0.01")
    reservation = worst_case_cost(
        model_id="claude-opus-5", input_tokens=1_000, max_output_tokens=3_000
    )

    with pytest.raises(ToolFailureError) as raised:
        governor(detected, investigated.run_id).reserve_or_raise(reservation)

    assert raised.value.code is ToolErrorCode.BUDGET_EXCEEDED
    assert "run budget" in str(raised.value)


def test_the_refusal_names_the_scope_that_failed(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """ "Over budget" without saying which budget is not actionable."""
    make_budget(detected, scope=BudgetScope.RUN, scope_ref=str(investigated.run_id), limit="100.00")
    make_budget(detected, scope=BudgetScope.GLOBAL, scope_ref=None, limit="0.001")

    refusal = governor(detected, investigated.run_id).check_affordable(Decimal("0.50"))

    assert refusal is not None
    assert refusal.scope is BudgetScope.GLOBAL


def test_scopes_are_an_and_not_a_precedence(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """A call inside its run budget can still break the monthly ceiling."""
    make_budget(detected, scope=BudgetScope.RUN, scope_ref=str(investigated.run_id), limit="10.00")
    make_budget(detected, scope=BudgetScope.GLOBAL, scope_ref=None, limit="25.00", consumed="24.99")

    assert governor(detected, investigated.run_id).check_affordable(Decimal("0.005")) is None
    assert governor(detected, investigated.run_id).check_affordable(Decimal("0.10")) is not None


def test_a_soft_budget_logs_and_continues(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    make_budget(
        detected,
        scope=BudgetScope.RUN,
        scope_ref=str(investigated.run_id),
        limit="0.001",
        hard_stop=False,
    )

    assert governor(detected, investigated.run_id).check_affordable(Decimal("5.00")) is None


def test_no_configured_budget_means_unbudgeted_not_blocked(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """A missing budget is a deliberate state, not an implicit limit of zero."""
    assert governor(detected, investigated.run_id).check_affordable(Decimal("999")) is None


# ---------------------------------------------------------------------------
# Non-monetary ceilings
# ---------------------------------------------------------------------------
def test_the_model_call_ceiling_halts_a_runaway_run(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """ "Cheap" and "bounded" are different properties."""
    for index in range(MAX_MODEL_CALLS_PER_RUN):
        detected.add(
            obs_orm.ModelCall(
                id=new_id(),
                run_id=investigated.run_id,
                node_name=f"loop-{index}",
                model_id="claude-opus-5",
                effort="high",
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
                latency_ms=0,
                stop_reason="fixture_replay",
                is_replay=True,
                trace_id="a" * 32,
                span_id=f"{index:016d}",
            )
        )
    detected.flush()

    with pytest.raises(ToolFailureError, match="ceiling"):
        governor(detected, investigated.run_id).check_call_ceilings()


def test_the_ceilings_match_the_documented_values() -> None:
    """`docs/cost-governance.md` §8."""
    assert MAX_MODEL_CALLS_PER_RUN == 12
    assert MAX_TOOL_CALLS_PER_RUN == 30


# ---------------------------------------------------------------------------
# A budget refusal is not a policy decision
# ---------------------------------------------------------------------------
def test_a_budget_refusal_is_never_recorded_as_a_policy_decision(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """Policy answers *may this happen*; cost answers *can we afford it*.

    Recording a budget refusal in `policy_evaluations` would claim a rule refused it
    when arithmetic did.
    """
    make_budget(detected, scope=BudgetScope.RUN, scope_ref=str(investigated.run_id), limit="0.0001")
    before = detected.scalar(sa.select(sa.func.count()).select_from(obs_orm.CostEntry))

    with pytest.raises(ToolFailureError):
        governor(detected, investigated.run_id).reserve_or_raise(Decimal("1.00"))

    from revenue_sentinel.db.models import governance as gov_orm

    decisions = detected.scalars(sa.select(gov_orm.PolicyEvaluation.decision)).all()
    after = detected.scalar(sa.select(sa.func.count()).select_from(obs_orm.CostEntry))

    # Only the three real policy decisions exist, and a refusal spent nothing.
    assert sorted(d.value for d in decisions) == [
        PolicyDecision.ALLOW.value,
        PolicyDecision.DENY.value,
        PolicyDecision.REQUIRE_APPROVAL.value,
    ]
    assert after == before


def test_budget_exceeded_forbids_retry_and_rerouting() -> None:
    from revenue_sentinel.mcp.errors import ERROR_POLICY

    policy = ERROR_POLICY[ToolErrorCode.BUDGET_EXCEEDED]
    assert policy.retry is False
    assert policy.alternative_route is False
