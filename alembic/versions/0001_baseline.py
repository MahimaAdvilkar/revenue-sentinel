"""Baseline schema -- all 29 tables and 26 native enum types.

The whole schema is created in one revision (`docs/data-model.md` §6). There are no
data migrations in v1: the database is disposable and re-seeded from fixtures.

`downgrade()` returns the database to genuinely empty. Alembic's autogenerate drops
tables but **not** the PostgreSQL enum types they used, which would leave a
downgraded database unable to re-run `upgrade()`. The explicit `DROP TYPE` block at
the end of `downgrade()` is what makes the round trip actually work, and
`tests/integration/test_migrations.py` asserts it.

Revision ID: 0001
Revises:
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ENUM_TYPE_NAMES: tuple[str, ...] = (
    "account_segment",
    "action_status",
    "action_type",
    "activity_direction",
    "activity_type",
    "approval_status",
    "budget_period",
    "budget_scope",
    "computed_by",
    "cost_type",
    "engagement_channel",
    "engagement_event_type",
    "evaluation_outcome",
    "event_type",
    "incident_status",
    "incident_type",
    "opportunity_stage",
    "policy_decision",
    "severity",
    "signal_type",
    "source_system",
    "support_severity",
    "support_status",
    "tool_call_status",
    "trust_level",
    "workflow_status",
)
"""Every native enum type this revision creates. Kept as data so `downgrade()` and
the migration test agree on the list by construction."""


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_ref", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "segment",
            sa.Enum("enterprise", "mid_market", "smb", name="account_segment"),
            nullable=False,
        ),
        sa.Column("industry", sa.String(length=255), nullable=False),
        sa.Column("employee_count", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint(
            "employee_count >= 0", name=op.f("ck_accounts_employee_count_non_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
    )
    op.create_index(op.f("ix_accounts_account_ref"), "accounts", ["account_ref"], unique=True)
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope", sa.Enum("global", "incident", "run", name="budget_scope"), nullable=False
        ),
        sa.Column("scope_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "period", sa.Enum("run", "incident", "monthly", name="budget_period"), nullable=False
        ),
        sa.Column("limit_usd", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "consumed_usd",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("hard_stop", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "limit_usd >= 0 AND consumed_usd >= 0", name=op.f("ck_budgets_amounts_non_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budgets")),
        sa.UniqueConstraint(
            "scope", "scope_ref", "period", name="uq_budgets_scope_scope_ref_period"
        ),
    )
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("suite_name", sa.String(length=255), nullable=False),
        sa.Column("suite_version", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("passed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "passed >= 0 AND total >= 0 AND passed <= total",
            name=op.f("ck_evaluation_runs_counts_coherent"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_runs")),
    )
    op.create_table(
        "raw_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "source_system",
            sa.Enum("crm", "product", "engagement", "support", "enrichment", name="source_system"),
            nullable=False,
        ),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ingest_batch_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_events")),
        sa.UniqueConstraint(
            "source_system", "source_event_id", name="uq_raw_events_source_system_source_event_id"
        ),
    )
    op.create_index(
        "ix_raw_events_ingest_batch_id", "raw_events", ["ingest_batch_id"], unique=False
    )
    op.create_table(
        "company_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("hq_country", sa.String(length=255), nullable=False),
        sa.Column("revenue_band", sa.String(length=255), nullable=False),
        sa.Column("tech_stack", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_company_profiles_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_profiles")),
        sa.UniqueConstraint("account_id", name=op.f("uq_company_profiles_account_id")),
    )
    op.create_table(
        "engagement_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "channel",
            sa.Enum("email", "calendar", "web", name="engagement_channel"),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            sa.Enum("sent", "opened", "clicked", "meeting_held", name="engagement_event_type"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_engagement_events_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_events")),
    )
    op.create_index(
        "ix_engagement_events_account_id_occurred_at",
        "engagement_events",
        ["account_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "normalized_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("raw_event_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "crm.opportunity.updated",
                "crm.activity.logged",
                "product.usage.rollup",
                "engagement.email.activity",
                "engagement.meeting.held",
                "support.issue.opened",
                "crm.opportunity.stage_changed",
                "crm.record.quality_flagged",
                "enrichment.provider.usage_reported",
                "campaign.performance.rollup",
                name="event_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "source_system",
            sa.Enum("crm", "product", "engagement", "support", "enrichment", name="source_system"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("account_ref", sa.String(length=255), nullable=True),
        sa.Column("opportunity_ref", sa.String(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "trust_level",
            sa.Enum("untrusted", name="trust_level"),
            server_default="untrusted",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["raw_event_id"],
            ["raw_events.id"],
            name=op.f("fk_normalized_events_raw_event_id_raw_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_normalized_events")),
        sa.UniqueConstraint("raw_event_id", name=op.f("uq_normalized_events_raw_event_id")),
    )
    op.create_index(
        "ix_normalized_events_account_ref", "normalized_events", ["account_ref"], unique=False
    )
    op.create_index(
        "ix_normalized_events_event_type_occurred_at",
        "normalized_events",
        ["event_type", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_normalized_events_opportunity_ref",
        "normalized_events",
        ["opportunity_ref"],
        unique=False,
    )
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_ref", sa.String(length=255), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "stage",
            sa.Enum(
                "discovery",
                "proposal",
                "negotiation",
                "closed_won",
                "closed_lost",
                name="opportunity_stage",
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("expected_close_date", sa.Date(), nullable=False),
        sa.Column("probability", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_opportunities_amount_non_negative")),
        sa.CheckConstraint(
            "probability >= 0 AND probability <= 1",
            name=op.f("ck_opportunities_probability_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_opportunities_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunities")),
    )
    op.create_index(
        "ix_opportunities_account_id_stage", "opportunities", ["account_id", "stage"], unique=False
    )
    op.create_index(
        op.f("ix_opportunities_opportunity_ref"), "opportunities", ["opportunity_ref"], unique=True
    )
    op.create_table(
        "support_issues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("external_ref", sa.String(length=255), nullable=False),
        sa.Column(
            "severity", sa.Enum("p1", "p2", "p3", "p4", name="support_severity"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum("open", "pending", "resolved", "closed", name="support_status"),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_support_issues_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_issues")),
        sa.UniqueConstraint("external_ref", name=op.f("uq_support_issues_external_ref")),
    )
    op.create_index(
        "ix_support_issues_account_id_status",
        "support_issues",
        ["account_id", "status"],
        unique=False,
    )
    op.create_table(
        "usage_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("active_users", sa.Integer(), nullable=False),
        sa.Column("sessions", sa.Integer(), nullable=False),
        sa.Column("feature_events", sa.Integer(), nullable=False),
        sa.Column("usage_score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint(
            "active_users >= 0 AND sessions >= 0 AND feature_events >= 0",
            name=op.f("ck_usage_snapshots_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "period_end >= period_start", name=op.f("ck_usage_snapshots_period_ordered")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_usage_snapshots_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_snapshots")),
        sa.UniqueConstraint("account_id", "period_start", name="uq_usage_snapshots_account_period"),
    )
    op.create_index(
        "ix_usage_snapshots_account_id_period_start",
        "usage_snapshots",
        ["account_id", "period_start"],
        unique=False,
    )
    op.create_table(
        "activities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "activity_type",
            sa.Enum("email", "call", "meeting", "note", name="activity_type"),
            nullable=False,
        ),
        sa.Column(
            "direction",
            sa.Enum("inbound", "outbound", "internal", name="activity_direction"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_activities_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_activities_opportunity_id_opportunities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activities")),
    )
    op.create_index(
        "ix_activities_account_id_occurred_at",
        "activities",
        ["account_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_activities_opportunity_id_occurred_at",
        "activities",
        ["opportunity_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "signal_type",
            sa.Enum(
                "stalled_opportunity",
                "renewal_risk",
                "deal_slippage",
                "pqa_discovery",
                "account_expansion",
                "crm_data_quality",
                "enrichment_cost_anomaly",
                "campaign_underperformance",
                name="signal_type",
            ),
            nullable=False,
        ),
        sa.Column("detector_version", sa.String(length=32), nullable=False),
        sa.Column(
            "severity",
            sa.Enum("low", "medium", "high", "critical", name="severity"),
            nullable=False,
        ),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_signals_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_signals_opportunity_id_opportunities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_signals_dedupe_key")),
    )
    op.create_index(
        "ix_signals_signal_type_detected_at",
        "signals",
        ["signal_type", "detected_at"],
        unique=False,
    )
    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_ref", sa.String(length=255), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "incident_type",
            sa.Enum(
                "stalled_opportunity",
                "renewal_risk",
                "deal_slippage",
                "pqa_discovery",
                "account_expansion",
                "crm_data_quality",
                "enrichment_cost_anomaly",
                "campaign_underperformance",
                name="incident_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "detected",
                "triaged",
                "investigating",
                "analyzed",
                "strategized",
                "awaiting_approval",
                "executing",
                "completed",
                "closed_rejected",
                "expired",
                "dismissed",
                "failed",
                name="incident_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("low", "medium", "high", "critical", name="severity"),
            nullable=False,
        ),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at", name=op.f("ck_incidents_closure_ordered")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_incidents_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_incidents_opportunity_id_opportunities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name=op.f("fk_incidents_signal_id_signals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_index(op.f("ix_incidents_incident_ref"), "incidents", ["incident_ref"], unique=True)
    op.create_index(
        "ix_incidents_status_opened_at", "incidents", ["status", "opened_at"], unique=False
    )
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("graph_version", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum("running", "interrupted", "completed", "failed", name="workflow_status"),
            nullable=False,
        ),
        sa.Column("current_node", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name=op.f("ck_workflow_runs_run_ordered")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_workflow_runs_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_runs")),
    )
    op.create_index(
        "ix_workflow_runs_incident_id_started_at",
        "workflow_runs",
        ["incident_id", "started_at"],
        unique=False,
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_audit_events_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_audit_events_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_incident_id_occurred_at",
        "audit_events",
        ["incident_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_run_id_occurred_at",
        "audit_events",
        ["run_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_run_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("check_name", sa.String(length=255), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum("passed", "failed", "skipped", name="evaluation_outcome"),
            nullable=False,
        ),
        sa.Column("expected", sa.Text(), nullable=False),
        sa.Column("actual", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
            name=op.f("fk_evaluation_results_evaluation_run_id_evaluation_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_evaluation_results_workflow_run_id_workflow_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_results")),
        sa.UniqueConstraint(
            "evaluation_run_id", "check_name", name="uq_evaluation_results_run_id_check_name"
        ),
    )
    op.create_index(
        "ix_evaluation_results_outcome", "evaluation_results", ["outcome"], unique=False
    )
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_ref", sa.String(length=16), nullable=False),
        sa.Column(
            "source_system",
            sa.Enum("crm", "product", "engagement", "support", "enrichment", name="source_system"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "trust_level",
            sa.Enum("untrusted", name="trust_level"),
            server_default="untrusted",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_evidence_items_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_items")),
        sa.UniqueConstraint("run_id", "evidence_ref", name="uq_evidence_items_run_id_evidence_ref"),
    )
    op.create_table(
        "hypotheses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("hypothesis_ref", sa.String(length=16), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name=op.f("ck_hypotheses_confidence_in_range")
        ),
        sa.CheckConstraint("rank >= 1", name=op.f("ck_hypotheses_rank_positive")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_hypotheses_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hypotheses")),
        sa.UniqueConstraint("run_id", "hypothesis_ref", name="uq_hypotheses_run_id_hypothesis_ref"),
        sa.UniqueConstraint("run_id", "rank", name="uq_hypotheses_run_id_rank"),
    )
    op.create_table(
        "impact_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("method_version", sa.String(length=32), nullable=False),
        sa.Column("pipeline_value", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("weighted_value", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("at_risk_value", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "computed_by",
            sa.Enum("deterministic", "model", name="computed_by"),
            server_default="deterministic",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "pipeline_value >= 0 AND weighted_value >= 0 AND at_risk_value >= 0",
            name=op.f("ck_impact_assessments_values_non_negative"),
        ),
        sa.CheckConstraint(
            "weighted_value <= pipeline_value AND at_risk_value <= weighted_value",
            name=op.f("ck_impact_assessments_values_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_impact_assessments_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impact_assessments")),
        sa.UniqueConstraint("run_id", name=op.f("uq_impact_assessments_run_id")),
    )
    op.create_table(
        "interventions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "action_type",
            sa.Enum(
                "crm_task",
                "email_draft",
                "crm_field_update",
                "slack_approval_request",
                name="action_type",
            ),
            nullable=False,
        ),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("expected_value", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("effort_score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("risk_score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("composite_score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expected_value >= 0", name=op.f("ck_interventions_expected_value_non_negative")
        ),
        sa.CheckConstraint("rank >= 1", name=op.f("ck_interventions_rank_positive")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_interventions_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interventions")),
        sa.UniqueConstraint("run_id", "rank", name="uq_interventions_run_id_rank"),
    )
    op.create_table(
        "model_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("effort", sa.String(length=16), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("stop_reason", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("span_id", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 "
            "AND cache_read_tokens >= 0 AND cache_write_tokens >= 0",
            name=op.f("ck_model_calls_tokens_non_negative"),
        ),
        sa.CheckConstraint("latency_ms >= 0", name=op.f("ck_model_calls_latency_non_negative")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_model_calls_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_calls")),
    )
    op.create_index(
        "ix_model_calls_run_id_node_name", "model_calls", ["run_id", "node_name"], unique=False
    )
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.Enum("success", "error", "denied", name="tool_call_status"), nullable=False
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("span_id", sa.String(length=16), nullable=False),
        sa.Column("parent_span_id", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("duration_ms >= 0", name=op.f("ck_tool_calls_duration_non_negative")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_tool_calls_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_calls")),
    )
    op.create_index(
        "ix_tool_calls_run_id_tool_name", "tool_calls", ["run_id", "tool_name"], unique=False
    )
    op.create_index("ix_tool_calls_trace_id", "tool_calls", ["trace_id"], unique=False)
    op.create_table(
        "workflow_transitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("from_node", sa.String(length=64), nullable=True),
        sa.Column("to_node", sa.String(length=64), nullable=False),
        sa.Column("edge_predicate", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("state_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "duration_ms >= 0", name=op.f("ck_workflow_transitions_duration_non_negative")
        ),
        sa.CheckConstraint(
            "sequence >= 0", name=op.f("ck_workflow_transitions_sequence_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_workflow_transitions_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_transitions")),
        sa.UniqueConstraint("run_id", "sequence", name="uq_workflow_transitions_run_id_sequence"),
    )
    op.create_index(
        "ix_workflow_transitions_run_id_sequence",
        "workflow_transitions",
        ["run_id", "sequence"],
        unique=False,
    )
    op.create_table(
        "action_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("intervention_id", sa.Uuid(), nullable=False),
        sa.Column(
            "action_type",
            sa.Enum(
                "crm_task",
                "email_draft",
                "crm_field_update",
                "slack_approval_request",
                name="action_type",
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "executing", "succeeded", "failed", "skipped", name="action_status"),
            nullable=False,
        ),
        sa.Column("authorized_by", sa.Uuid(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_ref", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_action_records_attempt_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["intervention_id"],
            ["interventions.id"],
            name=op.f("fk_action_records_intervention_id_interventions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_action_records_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_records")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_action_records_idempotency_key")),
    )
    op.create_index(
        "ix_action_records_run_id_status", "action_records", ["run_id", "status"], unique=False
    )
    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("decision_type", sa.String(length=64), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("inputs_digest", sa.String(length=64), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_call_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["model_call_id"],
            ["model_calls.id"],
            name=op.f("fk_agent_decisions_model_call_id_model_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_agent_decisions_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_decisions")),
    )
    op.create_index(
        "ix_agent_decisions_run_id_agent_name",
        "agent_decisions",
        ["run_id", "agent_name"],
        unique=False,
    )
    op.create_table(
        "cost_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("model_call_id", sa.Uuid(), nullable=True),
        sa.Column("tool_call_id", sa.Uuid(), nullable=True),
        sa.Column(
            "cost_type",
            sa.Enum("model_inference", "tool_invocation", name="cost_type"),
            nullable=False,
        ),
        sa.Column("amount_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("pricing_version", sa.String(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(model_call_id IS NULL) <> (tool_call_id IS NULL)",
            name=op.f("ck_cost_entries_exactly_one_source"),
        ),
        sa.CheckConstraint("amount_usd >= 0", name=op.f("ck_cost_entries_amount_non_negative")),
        sa.ForeignKeyConstraint(
            ["model_call_id"],
            ["model_calls.id"],
            name=op.f("fk_cost_entries_model_call_id_model_calls"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_cost_entries_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_call_id"],
            ["tool_calls.id"],
            name=op.f("fk_cost_entries_tool_call_id_tool_calls"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cost_entries")),
    )
    op.create_index(
        "ix_cost_entries_run_id_cost_type", "cost_entries", ["run_id", "cost_type"], unique=False
    )
    op.create_table(
        "hypothesis_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hypothesis_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["evidence_item_id"],
            ["evidence_items.id"],
            name=op.f("fk_hypothesis_evidence_evidence_item_id_evidence_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"],
            ["hypotheses.id"],
            name=op.f("fk_hypothesis_evidence_hypothesis_id_hypotheses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hypothesis_evidence")),
        sa.UniqueConstraint(
            "hypothesis_id",
            "evidence_item_id",
            name="uq_hypothesis_evidence_hypothesis_id_evidence_item_id",
        ),
    )
    op.create_table(
        "policy_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("intervention_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version", sa.String(length=16), nullable=False),
        sa.Column("risk_tier", sa.SmallInteger(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum("allow", "require_approval", "deny", name="policy_decision"),
            nullable=False,
        ),
        sa.Column("matched_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "risk_tier >= 0 AND risk_tier <= 3",
            name=op.f("ck_policy_evaluations_risk_tier_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["intervention_id"],
            ["interventions.id"],
            name=op.f("fk_policy_evaluations_intervention_id_interventions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_evaluations")),
        sa.UniqueConstraint("intervention_id", name=op.f("uq_policy_evaluations_intervention_id")),
    )
    op.create_index(
        "ix_policy_evaluations_decision", "policy_evaluations", ["decision"], unique=False
    )
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "expired", name="approval_status"),
            nullable=False,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expires_at > requested_at", name=op.f("ck_approval_requests_expiry_after_request")
        ),
        sa.ForeignKeyConstraint(
            ["policy_evaluation_id"],
            ["policy_evaluations.id"],
            name=op.f("fk_approval_requests_policy_evaluation_id_policy_evaluations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_approval_requests_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_requests")),
        sa.UniqueConstraint(
            "policy_evaluation_id", name=op.f("uq_approval_requests_policy_evaluation_id")
        ),
    )
    op.create_index(
        "ix_approval_requests_status_expires_at",
        "approval_requests",
        ["status", "expires_at"],
        unique=False,
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index("ix_approval_requests_status_expires_at", table_name="approval_requests")
    op.drop_table("approval_requests")
    op.drop_index("ix_policy_evaluations_decision", table_name="policy_evaluations")
    op.drop_table("policy_evaluations")
    op.drop_table("hypothesis_evidence")
    op.drop_index("ix_cost_entries_run_id_cost_type", table_name="cost_entries")
    op.drop_table("cost_entries")
    op.drop_index("ix_agent_decisions_run_id_agent_name", table_name="agent_decisions")
    op.drop_table("agent_decisions")
    op.drop_index("ix_action_records_run_id_status", table_name="action_records")
    op.drop_table("action_records")
    op.drop_index("ix_workflow_transitions_run_id_sequence", table_name="workflow_transitions")
    op.drop_table("workflow_transitions")
    op.drop_index("ix_tool_calls_trace_id", table_name="tool_calls")
    op.drop_index("ix_tool_calls_run_id_tool_name", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index("ix_model_calls_run_id_node_name", table_name="model_calls")
    op.drop_table("model_calls")
    op.drop_table("interventions")
    op.drop_table("impact_assessments")
    op.drop_table("hypotheses")
    op.drop_table("evidence_items")
    op.drop_index("ix_evaluation_results_outcome", table_name="evaluation_results")
    op.drop_table("evaluation_results")
    op.drop_index("ix_audit_events_run_id_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_incident_id_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_workflow_runs_incident_id_started_at", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_incidents_status_opened_at", table_name="incidents")
    op.drop_index(op.f("ix_incidents_incident_ref"), table_name="incidents")
    op.drop_table("incidents")
    op.drop_index("ix_signals_signal_type_detected_at", table_name="signals")
    op.drop_table("signals")
    op.drop_index("ix_activities_opportunity_id_occurred_at", table_name="activities")
    op.drop_index("ix_activities_account_id_occurred_at", table_name="activities")
    op.drop_table("activities")
    op.drop_index("ix_usage_snapshots_account_id_period_start", table_name="usage_snapshots")
    op.drop_table("usage_snapshots")
    op.drop_index("ix_support_issues_account_id_status", table_name="support_issues")
    op.drop_table("support_issues")
    op.drop_index(op.f("ix_opportunities_opportunity_ref"), table_name="opportunities")
    op.drop_index("ix_opportunities_account_id_stage", table_name="opportunities")
    op.drop_table("opportunities")
    op.drop_index("ix_normalized_events_opportunity_ref", table_name="normalized_events")
    op.drop_index("ix_normalized_events_event_type_occurred_at", table_name="normalized_events")
    op.drop_index("ix_normalized_events_account_ref", table_name="normalized_events")
    op.drop_table("normalized_events")
    op.drop_index("ix_engagement_events_account_id_occurred_at", table_name="engagement_events")
    op.drop_table("engagement_events")
    op.drop_table("company_profiles")
    op.drop_index("ix_raw_events_ingest_batch_id", table_name="raw_events")
    op.drop_table("raw_events")
    op.drop_table("evaluation_runs")
    op.drop_table("budgets")
    op.drop_index(op.f("ix_accounts_account_ref"), table_name="accounts")
    op.drop_table("accounts")

    # Native enum types are not dropped by autogenerate. Without this block the
    # database is left holding 26 orphaned types and `upgrade()` fails on re-run
    # with "type ... already exists".
    for enum_name in ENUM_TYPE_NAMES:
        op.execute(sa.text(f"DROP TYPE IF EXISTS {enum_name}"))
    # ### end Alembic commands ###
