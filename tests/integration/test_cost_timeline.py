"""The merged timeline, and the cost summary the CLI and demo print.

Two properties matter beyond "it returns rows": tracing metadata is **preserved where it
exists and absent where it does not** (never invented), and the ordering is total, so a
timeline is comparable between runs that share one injected timestamp.
"""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from revenue_sentinel.cli import render_cost_summary
from revenue_sentinel.cost.summary import summarise_run
from revenue_sentinel.cost.timeline import SOURCE_RANK, incident_timeline, traces_in
from revenue_sentinel.db.models import observability as obs_orm
from revenue_sentinel.domain.enums import CostType
from revenue_sentinel.orchestration import runner

INCIDENT = "INC-001"


def timeline(session: Session, outcome: runner.InvestigationOutcome) -> list[object]:
    return incident_timeline(session, run_id=outcome.run_id)  # type: ignore[arg-type,return-value]


# ---------------------------------------------------------------------------
# All four sources are present
# ---------------------------------------------------------------------------
def test_the_timeline_merges_all_four_sources(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    events = incident_timeline(detected, run_id=investigated.run_id)
    sources = {event.source for event in events}

    assert sources == {"model_call", "tool_call", "cost_entry", "audit_event"}


def test_the_timeline_includes_every_model_and_tool_call(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    events = incident_timeline(detected, run_id=investigated.run_id)

    model_rows = detected.scalar(
        sa.select(sa.func.count())
        .select_from(obs_orm.ModelCall)
        .where(obs_orm.ModelCall.run_id == investigated.run_id)
    )
    tool_rows = detected.scalar(
        sa.select(sa.func.count())
        .select_from(obs_orm.ToolCall)
        .where(obs_orm.ToolCall.run_id == investigated.run_id)
    )

    assert len([e for e in events if e.source == "model_call"]) == model_rows
    assert len([e for e in events if e.source == "tool_call"]) == tool_rows


def test_cost_entries_carry_their_amount_and_pricing_version(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    entries = [
        e
        for e in incident_timeline(detected, run_id=investigated.run_id)
        if e.source == "cost_entry"
    ]

    assert entries
    for entry in entries:
        assert entry.amount_usd == Decimal("0.000000")
        assert entry.pricing_version == "pricing/2026-08"


# ---------------------------------------------------------------------------
# Tracing metadata: preserved, never invented
# ---------------------------------------------------------------------------
def test_trace_correlation_is_preserved_across_sources(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """One run, one trace. If model and tool calls disagreed, correlation would be
    decorative."""
    events = incident_timeline(detected, run_id=investigated.run_id)

    assert len(traces_in(events)) == 1
    for event in events:
        if event.source in {"model_call", "tool_call"}:
            assert event.trace_id
            assert event.span_id


def test_spans_are_distinct_per_call(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    events = incident_timeline(detected, run_id=investigated.run_id)
    model_spans = [e.span_id for e in events if e.source == "model_call"]

    assert len(set(model_spans)) == len(model_spans), "each call needs its own span"


def test_tool_calls_preserve_parent_span(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    tools = [
        e
        for e in incident_timeline(detected, run_id=investigated.run_id)
        if e.source == "tool_call"
    ]

    assert tools
    assert any(event.parent_span_id for event in tools)


def test_missing_tracing_metadata_is_absent_rather_than_invented(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """`audit_events` carries no trace. Reporting `None` is the honest signal that those
    rows were never part of a traced call; a plausible-looking id would be a lie."""
    audits = [
        e
        for e in incident_timeline(detected, run_id=investigated.run_id)
        if e.source == "audit_event"
    ]

    assert audits
    assert all(e.trace_id is None and e.span_id is None for e in audits)


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------
def test_ordering_is_chronological_and_totally_determined(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """The whole run shares one injected timestamp, so without a tie-break the order
    would shuffle between runs and stop being comparable."""
    first = incident_timeline(detected, run_id=investigated.run_id)
    second = incident_timeline(detected, run_id=investigated.run_id)

    assert [e.sort_key for e in first] == sorted(e.sort_key for e in first)
    assert [(e.source, e.event_type, e.detail) for e in first] == [
        (e.source, e.event_type, e.detail) for e in second
    ]


def test_the_source_rank_covers_every_emitted_source(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """A source missing from the rank would raise on sort rather than order oddly."""
    events = incident_timeline(detected, run_id=investigated.run_id)
    assert {e.source for e in events} <= set(SOURCE_RANK)


# ---------------------------------------------------------------------------
# Summary reconciliation
# ---------------------------------------------------------------------------
def test_the_summary_totals_equal_the_sum_of_cost_entries(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    summary = summarise_run(detected, run_id=investigated.run_id, incident_ref=INCIDENT)
    ledger_total = detected.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(obs_orm.CostEntry.amount_usd), 0)).where(
            obs_orm.CostEntry.run_id == investigated.run_id
        )
    )

    assert summary.total_cost == Decimal(ledger_total or 0).quantize(Decimal("0.000001"))
    assert summary.model_cost + summary.tool_cost == summary.total_cost


def test_the_summary_counts_match_the_ledgers(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    summary = summarise_run(detected, run_id=investigated.run_id, incident_ref=INCIDENT)
    entries = detected.scalars(
        sa.select(obs_orm.CostEntry).where(obs_orm.CostEntry.run_id == investigated.run_id)
    ).all()

    assert summary.model_calls == len(
        [e for e in entries if e.cost_type is CostType.MODEL_INFERENCE]
    )
    assert summary.tool_calls == len(
        [e for e in entries if e.cost_type is CostType.TOOL_INVOCATION]
    )


def test_the_rendered_summary_shows_microdollar_precision(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """`$0.00` would hide sub-cent spend. The governance view never rounds to cents."""
    summary = summarise_run(detected, run_id=investigated.run_id, incident_ref=INCIDENT)
    rendered = "\n".join(render_cost_summary(summary))

    assert "$0.000000" in rendered
    assert "TOTAL              $0.000000" in rendered
    assert "pricing/2026-08" in rendered


def test_fixture_mode_has_cost_entries_rather_than_none(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """An absent row would be ambiguous between "free" and "not recorded"."""
    summary = summarise_run(detected, run_id=investigated.run_id, incident_ref=INCIDENT)

    assert summary.model_calls > 0
    assert summary.tool_calls > 0
    assert summary.total_cost == Decimal("0.000000")


def test_no_fabricated_token_counts_exist(
    investigated: runner.InvestigationOutcome, detected: Session
) -> None:
    """Every replayed call reports zero, because zero were consumed."""
    calls = detected.scalars(
        sa.select(obs_orm.ModelCall).where(obs_orm.ModelCall.run_id == investigated.run_id)
    ).all()

    assert calls
    for call in calls:
        assert call.is_replay is True
        assert (call.input_tokens, call.output_tokens) == (0, 0)
        assert (call.cache_read_tokens, call.cache_write_tokens) == (0, 0)
        assert call.stop_reason == "fixture_replay"
