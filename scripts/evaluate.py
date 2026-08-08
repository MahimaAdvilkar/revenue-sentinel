"""`make eval` -- run the deterministic evaluation against the golden workflow.

No model is consulted, so this costs exactly $0.000000 (ADR-0021). Exits non-zero when
any check fails, so CI treats an evaluation failure as a build failure.
"""

from __future__ import annotations

import sys

from revenue_sentinel.core.config import get_settings
from revenue_sentinel.core.errors import RevenueSentinelError
from revenue_sentinel.core.logging import configure_logging
from revenue_sentinel.cost import reporting as cost_reporting
from revenue_sentinel.db.session import build_engine, build_session_factory, session_scope
from revenue_sentinel.evaluation.service import evaluate, render

INCIDENT = "INC-001"


def main() -> int:
    settings = get_settings()
    configure_logging(level="WARNING", log_format=settings.log_format)
    factory = build_session_factory(build_engine(settings))

    try:
        with session_scope(factory) as session:
            run_id = cost_reporting.latest_run_id(session, INCIDENT)
            evaluation = evaluate(session, run_id=run_id, occurred_at=settings.evaluation_timestamp)
            lines = render(evaluation, incident_ref=INCIDENT)
            ok = evaluation.ok
    except RevenueSentinelError as error:
        print(f"error: {error}")
        print("Run `make demo` first -- evaluation needs a completed workflow.")
        return 1

    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
