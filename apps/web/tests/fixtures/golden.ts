/**
 * Golden-run response shapes, typed against the generated contract.
 *
 * These are annotated with the generated types, so if the backend renames a field this
 * file stops compiling -- the fixtures cannot drift away from the API the way a
 * hand-written mock would.
 */
import type {
  ApprovalInbox,
  CostCentre,
  CostSummary,
  EvaluationHistory,
  IntegrationCatalogue,
  Investigation,
  Intervention,
  Overview,
  Timeline,
  UncertainActions,
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

// ---------------------------------------------------------------------------
// Session 10 centres.
// ---------------------------------------------------------------------------

export const costCentre: CostCentre = {
  total_cost: "0.000000",
  model_cost: "0.000000",
  tool_cost: "0.000000",
  model_calls: 4,
  tool_calls: 9,
  pricing_versions: ["2026-08-01"],
  budgets: [
    {
      scope: "global",
      scope_ref: null,
      limit_usd: "25.000000",
      consumed_usd: "0.000150",
      remaining_usd: "24.999850",
      hard_stop: true,
    },
  ],
  by_incident: [
    {
      incident_ref: "INC-001",
      model_cost: "0.000000",
      tool_cost: "0.000000",
      total_cost: "0.000000",
      model_calls: 4,
      tool_calls: 9,
    },
  ],
  model_mix: [
    {
      model_id: "claude-sonnet-5",
      calls: 4,
      cost_usd: "0.000000",
      replayed: 4,
    },
  ],
  cache_effectiveness: {
    observed: false,
    value: null,
    note:
      "Never observed. No live API call has been made, so no cache hit has ever " +
      "occurred. This is an absence of data, not a hit rate of zero.",
  },
  concurrency_note:
    "GLOBAL budget enforcement is not atomic across concurrent independent runs. " +
    "Read-then-call is sound only because model calls are serialized within a run " +
    "(ADR-0019).",
};

/** Two attempts: an earlier failure, then a pass. The failure must survive. */
export const evaluationHistory: EvaluationHistory = {
  runs: [
    {
      evaluation_run_id: "11111111-1111-1111-1111-111111111111",
      sequence: 2,
      suite_name: "golden-scenario",
      evaluator_version: "1.0.0",
      started_at: "2026-08-01T12:00:00Z",
      passed: 6,
      total: 6,
      outcome: "passed",
    },
    {
      evaluation_run_id: "22222222-2222-2222-2222-222222222222",
      sequence: 1,
      suite_name: "golden-scenario",
      evaluator_version: "1.0.0",
      started_at: "2026-08-01T12:00:00Z",
      passed: 4,
      total: 6,
      outcome: "failed",
    },
  ],
  llm_judge_used: false,
  evaluation_cost: "0.000000",
};

export const evaluationLatest = {
  suite_name: "golden-scenario",
  evaluator_version: "1.0.0",
  passed: 6,
  total: 6,
  llm_judge_used: false,
  evaluation_cost: "0.000000",
  results: [
    {
      check_name: "incident_detected",
      outcome: "passed",
      expected: "INC-001 open",
      actual: "INC-001 open",
      detail: null,
    },
  ],
};

/** Two adapters, both declaring SIMULATED, with roadmap copy the adapters wrote. */
export const integrations: IntegrationCatalogue = {
  integrations: [
    {
      name: "CRM",
      module: "integrations/simulated/crm.py",
      integration_status: "SIMULATED",
      port: "integrations/ports/crm.py",
      summary: "CRM adapter -- SIMULATED.",
      when_real: [
        { heading: "API", body: "HubSpot CRM v3 or Salesforce REST v60." },
        { heading: "Auth", body: "OAuth 2.0 authorisation-code flow with refresh tokens." },
        { heading: "Rate limits", body: "HubSpot: 100 requests / 10s per portal." },
        { heading: "Pagination", body: "Both cursor-paginate." },
      ],
      when_real_documented: true,
    },
    {
      name: "Messaging",
      module: "integrations/simulated/messaging.py",
      integration_status: "SIMULATED",
      port: "integrations/ports/messaging.py",
      summary: "Messaging adapter -- SIMULATED.",
      when_real: [
        { heading: "API", body: "Gmail users.drafts.create, or Microsoft Graph /me/messages." },
        { heading: "Auth", body: "Gmail needs gmail.compose -- a write scope on a mailbox." },
        { heading: "Rate limits", body: "Gmail: 250 quota units/user/second." },
        { heading: "Idempotency", body: "Gmail draft creation is not idempotent." },
      ],
      when_real_documented: true,
    },
  ],
  any_real: false,
};

/**
 * The same catalogue with one adapter bound for real.
 *
 * This shape cannot occur in v1 -- which is exactly why it is a fixture. The screen's
 * behaviour when an integration stops being simulated is the behaviour nobody can test by
 * waiting for it.
 */
export const integrationsWithOneReal: IntegrationCatalogue = {
  integrations: [
    { ...integrations.integrations[0]!, integration_status: "IMPLEMENTED" },
    integrations.integrations[1]!,
  ],
  any_real: true,
};

/** One action left uncertain: claimed, then the process died before recording. */
export const uncertainActions: UncertainActions = {
  incident_ref: "INC-001",
  actions: [
    {
      action_record_id: "11111111-1111-1111-1111-111111111111",
      action_type: "crm_task",
      status: "indeterminate",
      target_ref: "OPP-2001",
      idempotency_key: "idem-uncertain-0001",
      attempt_count: 1,
      authorized_by: "22222222-2222-2222-2222-222222222222",
      approval_request_id: null,
      reconciled_by: null,
      reconciled_at: null,
      reconciliation_evidence: null,
      reconcile_command:
        "uv run rs reconcile 11111111-1111-1111-1111-111111111111 " +
        "--outcome occurred|did-not-occur --as usr:your-name --evidence '<what you saw>'",
    },
  ],
  delivery_note:
    "Execution is at-least-once with an explicit unknown (ADR-0017). Reconciliation " +
    "records what a person attests happened; it does not make delivery exactly-once.",
};
