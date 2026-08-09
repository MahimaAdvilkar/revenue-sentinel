/**
 * Golden-run response shapes, typed against the generated contract.
 *
 * These are annotated with the generated types, so if the backend renames a field this
 * file stops compiling -- the fixtures cannot drift away from the API the way a
 * hand-written mock would.
 */
import type {
  ApprovalInbox,
  CostSummary,
  Investigation,
  Intervention,
  Overview,
  Timeline,
} from "@/lib/api";

export const overview: Overview = {
  total_at_risk: "32130.00",
  total_weighted: "108000.00",
  open_incidents: 0,
  incidents_by_status: { completed: 1 },
  integration_status: "SIMULATED",
};

export const investigation: Investigation = {
  incident_ref: "INC-001",
  evidence: [
    {
      evidence_ref: "EV-001",
      source_system: "crm",
      tool_name: "crm_get_opportunity",
      trust_level: "untrusted",
      content: { stage: "proposal" },
      integration_status: "SIMULATED",
    },
  ],
  hypotheses: [
    {
      hypothesis_ref: "HYP-001",
      statement: "The buying committee is evaluating while the seller has gone quiet.",
      confidence: "0.7200",
      rank: 1,
      cites: ["EV-002", "EV-004"],
    },
  ],
  impact: {
    pipeline_value: "180000.00",
    weighted_value: "108000.00",
    at_risk_value: "32130.00",
    currency: "USD",
    computed_by: "deterministic",
    method_version: "pipeline_impact/v1",
  },
};

export const interventions: Intervention[] = [
  {
    rank: 1,
    title: "Book a proposal review with the economic buyer",
    action_type: "crm_task",
    rationale: "Usage is climbing while sales contact has stopped.",
    target_ref: "OPP-2001",
    expected_value: "16065.00",
    composite_score: "4.96",
    decision: "allow",
    risk_tier: 1,
    matched_rules: ["tier1:internal-reversible"],
    reason: "Internal and reversible.",
    executed: true,
    action_status: "succeeded",
    integration_status: "SIMULATED",
  },
];

/** Deliberately out of timestamp order to prove the UI does not re-sort. */
export const timeline: Timeline = {
  incident_ref: "INC-001",
  trace_count: 1,
  events: [
    {
      occurred_at: "2026-08-01T12:00:00+00:00",
      source: "audit_event",
      event_type: "incident.opened",
      detail: "agent:signal_agent",
      trace_id: null,
      span_id: null,
      parent_span_id: null,
      amount_usd: null,
      pricing_version: null,
      integration_status: null,
    },
    {
      occurred_at: "2026-08-01T12:00:00+00:00",
      source: "model_call",
      event_type: "plan_investigation",
      detail: "claude-opus-5 in=0 out=0 [replay]",
      trace_id: "a".repeat(32),
      span_id: "b".repeat(16),
      parent_span_id: null,
      amount_usd: null,
      pricing_version: null,
      integration_status: null,
    },
    {
      occurred_at: "2026-08-01T12:00:00+00:00",
      source: "cost_entry",
      event_type: "model_inference",
      detail: "$0.000000",
      trace_id: null,
      span_id: null,
      parent_span_id: null,
      amount_usd: "0.000000",
      pricing_version: "pricing/2026-08",
      integration_status: null,
    },
  ],
};

export const cost: CostSummary = {
  incident_ref: "INC-001",
  model_cost: "0.000000",
  tool_cost: "0.000000",
  total_cost: "0.000000",
  model_calls: 4,
  tool_calls: 7,
  pricing_versions: ["pricing/2026-08"],
  concurrency_note:
    "Budgets are checked read-then-call and are safe only because model calls are serialized within a run. Two concurrent runs sharing a GLOBAL budget can race (ADR-0019).",
  ledger: [
    { kind: "model", cost_type: "model_inference", amount_usd: "0.000000", pricing_version: "pricing/2026-08" },
    { kind: "tool", cost_type: "tool_invocation", amount_usd: "0.000000", pricing_version: "pricing/2026-08" },
  ],
};

export const approvals: ApprovalInbox = {
  pending: [
    {
      approval_ref: "APR-001",
      status: "pending",
      requested_by: "agent:policy_and_risk",
      expires_at: "2026-08-02T12:00:00+00:00",
      intervention_title: "Send the champion a usage-insight summary",
      approve_command: "uv run rs approve APR-001 --as usr:your-name",
      integration_status: "SIMULATED",
    },
  ],
  identity_note:
    "Approval is available on the CLI only. `--as` is a CLAIMED identity, not an authenticated one: this system has no authentication (ADR-0018).",
};
