"""The one live smoke test. **Never run in this project, and never in CI.**

`make smoke-live` ran `pytest -m live` against zero marked tests for three sessions: it
exited without collecting anything, which reads as a pass. A gate that cannot fail is
worse than no gate, so this is a real test -- and it stays unrun.

It is the only place a live model call could originate from a test. Everything about it
is opt-in: the marker excludes it by default, the fixtures below refuse unless the mode
and the credential are both explicitly present, and CI never selects the marker.

**What it would prove if run:** that the live client returns a response satisfying the
same structured-output schema the fixtures satisfy -- that is, that the pipeline is not
secretly fixture-shaped. **What it would not prove:** anything about answer quality. One
live call is not an evaluation (ADR-0021).
"""

from __future__ import annotations

import pytest

from revenue_sentinel.core.config import Settings, get_settings
from revenue_sentinel.intelligence.factory import build_llm_client
from revenue_sentinel.intelligence.prompts import PLANNER_SYSTEM_PROMPT
from revenue_sentinel.intelligence.schemas import InvestigationPlan

pytestmark = pytest.mark.live


@pytest.fixture
def live_settings() -> Settings:
    """Refuses unless a live mode *and* a credential are configured."""
    settings = get_settings()
    if settings.demo_mode == "fixture":
        pytest.fail("smoke-live requires DEMO_MODE=live; fixture mode never calls the API")
    if settings.anthropic_api_key is None:
        pytest.fail("smoke-live requires ANTHROPIC_API_KEY")
    return settings


def test_the_live_client_returns_a_schema_valid_plan(live_settings: Settings) -> None:
    """One billable call. Asserts structure, and claims nothing about quality."""
    from revenue_sentinel.intelligence.ports import LLMRequest

    client = build_llm_client(live_settings)
    response = client.complete_structured(
        LLMRequest(
            node_name="plan_investigation",
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_content=(
                "<incident>Smoke test. Opportunity OPP-2001 has been inactive for 14 "
                "days while product usage rose.</incident>"
            ),
            output_schema=InvestigationPlan,
            model_id=live_settings.model_default,
            effort=live_settings.model_effort_default,
        )
    )

    assert isinstance(response.output, InvestigationPlan)
    assert response.output.steps, "a plan with no steps would not be a plan"
    assert response.is_replay is False, "this test exists to exercise the live path"
    assert response.input_tokens > 0, "a live call consumes tokens; a replay reports zero"
