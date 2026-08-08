"""The budget gate on the model-call path: refused *before* the client is reached.

The assertion that matters is not "an error was raised" -- it is that a counting fake
client recorded **zero** calls. "The call failed" and "the call never happened" are
different facts, and only the second is budget enforcement.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import Session

from revenue_sentinel.core.ids import new_id
from revenue_sentinel.cost import estimation
from revenue_sentinel.cost.client import BudgetedLLMClient
from revenue_sentinel.cost.governor import CostGovernor
from revenue_sentinel.cost.pricing import cost_of, worst_case_cost
from revenue_sentinel.cost.routing import route_for
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import BudgetPeriod, BudgetScope
from revenue_sentinel.intelligence.ports import LLMRequest, LLMResponse
from revenue_sentinel.intelligence.schemas import InvestigationPlan
from revenue_sentinel.mcp.errors import ToolErrorCode, ToolFailureError
from revenue_sentinel.orchestration import runner

INCIDENT = "INC-001"


class CountingLLMClient:
    """Records whether it was reached at all. Never returns a real response."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete_structured[T: BaseModel](self, request: LLMRequest[T]) -> LLMResponse[T]:
        self.calls.append(request.node_name)
        raise AssertionError("the fake client should not need to produce a response")


def plan_request() -> LLMRequest[InvestigationPlan]:
    return LLMRequest(
        node_name="plan_investigation",
        system_prompt="You are the Investigation Planner." * 20,
        user_content="<incident>...</incident>" * 40,
        output_schema=InvestigationPlan,
        model_id="claude-opus-5",
        effort="high",
    )


def make_budget(session: Session, *, scope: BudgetScope, scope_ref: str | None, limit: str) -> None:
    session.add(
        obs_orm.Budget(
            id=new_id(),
            scope=scope,
            scope_ref=scope_ref,
            period=BudgetPeriod.MONTHLY if scope is BudgetScope.GLOBAL else BudgetPeriod.RUN,
            limit_usd=Decimal(limit),
            consumed_usd=Decimal("0"),
            hard_stop=True,
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# The gate fires before the client
# ---------------------------------------------------------------------------
def test_an_exhausted_budget_prevents_the_client_from_being_called(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """The whole claim, in one assertion: `fake.calls == []`."""
    make_budget(
        detected,
        scope=BudgetScope.RUN,
        scope_ref=str(investigated.run_id),
        limit="0.000001",
    )
    fake = CountingLLMClient()
    client = BudgetedLLMClient(
        fake, CostGovernor(detected, run_id=investigated.run_id, incident_ref=INCIDENT)
    )

    with pytest.raises(ToolFailureError) as raised:
        client.complete_structured(plan_request())

    assert raised.value.code is ToolErrorCode.BUDGET_EXCEEDED
    assert fake.calls == [], "the client was reached despite an exhausted budget"


def test_an_affordable_call_reaches_the_client(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """The gate must admit as well as refuse, or it proves nothing."""
    make_budget(detected, scope=BudgetScope.RUN, scope_ref=str(investigated.run_id), limit="100.00")
    fake = CountingLLMClient()
    client = BudgetedLLMClient(
        fake, CostGovernor(detected, run_id=investigated.run_id, incident_ref=INCIDENT)
    )

    with pytest.raises(AssertionError, match="should not need to produce"):
        client.complete_structured(plan_request())

    assert fake.calls == ["plan_investigation"]


def test_the_reservation_prices_the_routed_model_not_a_generic_one(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """A budget priced against the wrong model is not a budget."""
    request = plan_request()
    route = route_for(request.node_name)
    estimated = estimation.estimate_input_tokens(
        system_prompt=request.system_prompt,
        user_content=request.user_content,
        output_schema=request.output_schema,
    )
    expected = worst_case_cost(
        model_id=route.model_id,
        input_tokens=estimated,
        max_output_tokens=route.max_output_tokens,
    )

    # A limit one microdollar under the exact reservation must refuse; at it, admit.
    make_budget(
        detected,
        scope=BudgetScope.RUN,
        scope_ref=str(investigated.run_id),
        limit=str(expected - Decimal("0.000001")),
    )
    fake = CountingLLMClient()
    client = BudgetedLLMClient(
        fake, CostGovernor(detected, run_id=investigated.run_id, incident_ref=INCIDENT)
    )

    with pytest.raises(ToolFailureError):
        client.complete_structured(plan_request())
    assert fake.calls == []
    assert route.model_id == "claude-opus-5"


# ---------------------------------------------------------------------------
# The estimator
# ---------------------------------------------------------------------------
def test_the_estimator_is_deterministic() -> None:
    request = plan_request()
    values = {
        estimation.estimate_input_tokens(
            system_prompt=request.system_prompt,
            user_content=request.user_content,
            output_schema=request.output_schema,
        )
        for _ in range(20)
    }
    assert len(values) == 1


def test_the_estimator_counts_prompt_content_and_schema() -> None:
    """Omitting the schema would under-count by the largest structured component."""
    with_schema = estimation.estimate_input_tokens(
        system_prompt="a" * 300, user_content="b" * 300, output_schema=InvestigationPlan
    )
    prose_only = (
        estimation.estimate_tokens("a" * 300)
        + estimation.estimate_tokens("b" * 300)
        + estimation.MESSAGE_OVERHEAD_TOKENS
    )

    assert with_schema > prose_only
    assert estimation.schema_overhead(InvestigationPlan) > 0


def test_the_estimator_rounds_up_and_never_under_counts() -> None:
    """Under-estimating admits a call that should have been refused."""
    assert estimation.estimate_tokens("a") == 1
    assert estimation.estimate_tokens("a" * 4) == 2
    assert estimation.estimate_tokens("") == 0
    assert estimation.CHARS_PER_TOKEN < 4, "the divisor must over-count, not under-count"


def test_the_estimator_never_writes_usage(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """The estimate is admission control, never billing truth. It must not reach
    `model_calls` -- the provider's counts are the only usage this system records."""
    make_budget(detected, scope=BudgetScope.RUN, scope_ref=str(investigated.run_id), limit="100.00")
    before = detected.scalars(
        sa.select(obs_orm.ModelCall).where(obs_orm.ModelCall.run_id == investigated.run_id)
    ).all()
    snapshot = [(c.id, c.input_tokens, c.output_tokens) for c in before]

    fake = CountingLLMClient()
    client = BudgetedLLMClient(
        fake, CostGovernor(detected, run_id=investigated.run_id, incident_ref=INCIDENT)
    )
    with pytest.raises(AssertionError):
        client.complete_structured(plan_request())

    after = detected.scalars(
        sa.select(obs_orm.ModelCall).where(obs_orm.ModelCall.run_id == investigated.run_id)
    ).all()
    assert [(c.id, c.input_tokens, c.output_tokens) for c in after] == snapshot


# ---------------------------------------------------------------------------
# Reserved is not spent
# ---------------------------------------------------------------------------
def test_actual_usage_becomes_consumed_spend_not_the_reservation(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """The reservation decides admission and is then discarded.

    A worst case of thousands of output tokens must not consume budget when the call
    actually returned two hundred.
    """
    from revenue_sentinel.cost import ledger as cost_ledger

    make_budget(detected, scope=BudgetScope.RUN, scope_ref=str(investigated.run_id), limit="100.00")
    reservation = worst_case_cost(
        model_id="claude-opus-5", input_tokens=1_000, max_output_tokens=3_000
    )

    call = obs_orm.ModelCall(
        id=new_id(),
        run_id=investigated.run_id,
        node_name="probe",
        model_id="claude-opus-5",
        effort="high",
        input_tokens=1_000,
        output_tokens=200,
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

    actual = cost_of(model_id="claude-opus-5", input_tokens=1_000, output_tokens=200)
    assert entry.amount_usd == actual
    assert actual < reservation, "the reservation should have been the larger figure"
    assert budget is not None
    assert budget.consumed_usd == actual, "the reservation must not have been charged"


def test_a_refused_call_charges_nothing(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """No double-charge, and no charge at all for a call that never happened."""
    make_budget(
        detected,
        scope=BudgetScope.RUN,
        scope_ref=str(investigated.run_id),
        limit="0.000001",
    )
    entries_before = detected.scalar(sa.select(sa.func.count()).select_from(obs_orm.CostEntry))

    fake = CountingLLMClient()
    client = BudgetedLLMClient(
        fake, CostGovernor(detected, run_id=investigated.run_id, incident_ref=INCIDENT)
    )
    with pytest.raises(ToolFailureError):
        client.complete_structured(plan_request())

    budget = detected.scalar(
        sa.select(obs_orm.Budget).where(obs_orm.Budget.scope_ref == str(investigated.run_id))
    )
    assert budget is not None
    assert budget.consumed_usd == Decimal("0")
    assert (
        detected.scalar(sa.select(sa.func.count()).select_from(obs_orm.CostEntry)) == entries_before
    )


# ---------------------------------------------------------------------------
# Fixture mode passes through the gate and still costs nothing
# ---------------------------------------------------------------------------
def test_fixture_mode_passes_through_governance_and_stays_at_zero(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """Computing a theoretical worst case must not make an offline run look like it
    spent money."""
    from revenue_sentinel.cost import ledger as cost_ledger

    assert cost_ledger.run_total(detected, investigated.run_id) == Decimal("0.000000")

    budgets = detected.scalars(sa.select(obs_orm.Budget)).all()
    assert all(budget.consumed_usd == Decimal("0") for budget in budgets)

    calls = detected.scalars(
        sa.select(obs_orm.ModelCall).where(obs_orm.ModelCall.run_id == investigated.run_id)
    ).all()
    assert calls
    assert all(c.is_replay and c.input_tokens == 0 and c.output_tokens == 0 for c in calls)
