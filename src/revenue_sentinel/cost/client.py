"""The budget gate on the model-call path.

`BudgetedLLMClient` wraps any `LLMClient` and refuses before delegating. The ordering is
the contract, and it is why this is a decorator rather than a check somewhere convenient:

    route -> non-monetary ceiling -> estimate input -> monetary reservation
          -> **client call** -> actual usage -> price -> cost_entry -> consumed_usd

`BUDGET_EXCEEDED` is raised **before** `inner.complete_structured` is reached. A test
proves it with a counting fake that records zero calls.

**Reserved is not spent.** The worst-case figure decides admission and is then discarded;
nothing writes it anywhere. Only actual provider usage becomes `consumed_usd`, so a
refused-then-allowed sequence cannot double-charge and an over-reservation cannot
permanently consume budget it never spent (ADR-0019).

**Fixture mode passes through this gate unchanged** -- it is admission control, not
metering. A replayed call is still checked against the ceilings, still makes no network
call, still reports zero tokens, and still costs `$0.000000`. Computing a theoretical
worst case must not make an offline run look like it spent money.

**Concurrency.** Read-consumed -> check -> call is sufficient *only* because model calls
here are serialized: LangGraph runs the nodes sequentially, one incident at a time, over a
synchronous session (ADR-0009). Two concurrent runs sharing a `GLOBAL` budget could both
pass against the same remaining balance. That is documented rather than defended against,
and ADR-0019 names the trigger for atomic reservation.
"""

from __future__ import annotations

from pydantic import BaseModel

from revenue_sentinel.core.logging import get_logger
from revenue_sentinel.cost.estimation import estimate_input_tokens
from revenue_sentinel.cost.governor import CostGovernor
from revenue_sentinel.cost.pricing import worst_case_cost
from revenue_sentinel.cost.routing import route_for
from revenue_sentinel.intelligence.ports import LLMClient, LLMRequest, LLMResponse

logger = get_logger(__name__)


class BudgetedLLMClient:
    """Admission control in front of a real client. Adds no metering of its own."""

    def __init__(self, inner: LLMClient, governor: CostGovernor) -> None:
        self._inner = inner
        self._governor = governor

    def complete_structured[T: BaseModel](self, request: LLMRequest[T]) -> LLMResponse[T]:
        # Routing first: the governor must price the model that will actually be called,
        # not a generic one. A call site with no route raises rather than defaulting.
        route = route_for(request.node_name)

        self._governor.check_call_ceilings()

        estimated_input = estimate_input_tokens(
            system_prompt=request.system_prompt,
            user_content=request.user_content,
            output_schema=request.output_schema,
        )
        reservation = worst_case_cost(
            model_id=route.model_id,
            input_tokens=estimated_input,
            max_output_tokens=route.max_output_tokens,
        )

        # Raises BUDGET_EXCEEDED here -- before the line below.
        self._governor.reserve_or_raise(reservation)

        logger.debug(
            "budget_admitted",
            node=request.node_name,
            model=route.model_id,
            estimated_input_tokens=estimated_input,
            reserved_usd=str(reservation),
            note="reserved is an admission bound, not spend",
        )

        return self._inner.complete_structured(request)
