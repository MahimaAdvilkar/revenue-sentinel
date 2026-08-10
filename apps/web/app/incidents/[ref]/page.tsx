/**
 * Incident detail -- "What happened on this deal, why, and what did it cost?"
 *
 * Two rules this screen obeys that are easy to break by accident:
 *
 * * **Timeline order is the API's.** The backend applies a total order (timestamp, then
 *   source rank, then content) precisely because the whole run shares one injected
 *   timestamp. Re-sorting here would produce a second, different answer to "what
 *   happened first".
 * * **Missing tracing metadata renders as absent.** `audit_events` carry no trace, the
 *   API returns `null`, and this shows "not recorded" rather than a dash that could be
 *   mistaken for an ID or an empty string that looks like a bug.
 */
import { Absent, Decision, ErrorNote, Section, Stat } from "@/components/Primitives";
import { SimulatedBadge } from "@/components/Simulated";
import { api, optional } from "@/lib/api";
import {
  formatConfidence,
  formatCost,
  formatMoney,
  formatTimestamp,
  shortId,
  titleCase,
} from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function IncidentDetailPage({
  params,
}: {
  params: Promise<{ ref: string }>;
}) {
  const { ref } = await params;

  const [incident, investigation, interventions, timeline, cost, uncertain] = await Promise.all([
    optional(() => api.incident(ref)),
    optional(() => api.investigation(ref)),
    optional(() => api.interventions(ref)),
    optional(() => api.timeline(ref)),
    optional(() => api.cost(ref)),
    optional(() => api.uncertainActions(ref)),
  ]);

  if (!incident) return <ErrorNote message={`No incident ${ref}.`} />;

  return (
    <>
      <h1>
        {incident.incident_ref} — {incident.title}
      </h1>
      <p className="subtitle">
        {incident.account.name} · {incident.opportunity?.opportunity_ref ?? "no opportunity"} ·{" "}
        {titleCase(incident.status)} · {titleCase(incident.severity)}
        <SimulatedBadge isSimulated={incident.account.is_simulated} />
      </p>

      {investigation?.impact ? (
        <div className="stat-grid">
          <Stat label="Pipeline" value={formatMoney(investigation.impact.pipeline_value, investigation.impact.currency)} />
          <Stat label="Weighted" value={formatMoney(investigation.impact.weighted_value, investigation.impact.currency)} />
          <Stat
            label="At risk"
            value={formatMoney(investigation.impact.at_risk_value, investigation.impact.currency)}
            hint={`${investigation.impact.computed_by} · ${investigation.impact.method_version}`}
          />
          <Stat label="Total spend" value={formatCost(cost?.total_cost)} />
        </div>
      ) : (
        <p className="subtitle">Not investigated yet.</p>
      )}

      {investigation ? (
        <Section title={`Evidence (${investigation.evidence.length})`} subtitle="All ingested content is untrusted (rule 14).">
          <table>
            <thead>
              <tr><th>Ref</th><th>Source</th><th>Tool</th><th>Trust</th></tr>
            </thead>
            <tbody>
              {investigation.evidence.map((item) => (
                <tr key={item.evidence_ref}>
                  <td className="mono">{item.evidence_ref}</td>
                  <td>{item.source_system}</td>
                  <td className="mono">
                    {item.tool_name}
                    <SimulatedBadge status={item.integration_status} />
                  </td>
                  <td>{item.trust_level}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      ) : null}

      {investigation && investigation.hypotheses.length > 0 ? (
        <Section title={`Hypotheses (${investigation.hypotheses.length})`} subtitle="Every citation resolves to a real evidence row — enforced by foreign keys.">
          {investigation.hypotheses.map((h) => (
            <div className="card" key={h.hypothesis_ref}>
              <div>
                <strong>{h.hypothesis_ref}</strong> · confidence {formatConfidence(h.confidence)}
              </div>
              <p>{h.statement}</p>
              <div className="rules">cites {h.cites.join(", ") || "—"}</div>
            </div>
          ))}
        </Section>
      ) : null}

      {interventions && interventions.length > 0 ? (
        <Section title={`Interventions (${interventions.length})`} subtitle="Drafted by a model, ranked by analytics/ — never by the model.">
          {interventions.map((item) => (
            <div className="card" key={item.rank}>
              <div>
                <strong>{item.rank}. {item.title}</strong>
                <SimulatedBadge status={item.integration_status} />
              </div>
              <div className="rules">
                {item.action_type} · expected {formatMoney(item.expected_value)} · score {item.composite_score}
              </div>
              <div style={{ marginTop: "0.4rem" }}>
                <Decision decision={item.decision} />
                {item.risk_tier !== null ? <span className="rules"> · tier {item.risk_tier}</span> : null}
                {item.executed ? <span className="rules"> · executed ({item.action_status})</span> : <span className="rules"> · not executed</span>}
              </div>
              <div className="rules">rules: {item.matched_rules.join(", ") || "—"}</div>
              {item.reason ? <div className="rules">{item.reason}</div> : null}
            </div>
          ))}
        </Section>
      ) : null}

      {uncertain && uncertain.actions.length > 0 ? (
        <Section
          title={`Uncertain actions (${uncertain.actions.length})`}
          subtitle="Claimed, then the process died before recording the outcome. The effect may or may not have happened."
        >
          <p className="caveat" data-testid="delivery-note">{uncertain.delivery_note}</p>
          <table>
            <thead>
              <tr>
                <th>Action</th><th>Target</th><th>Status</th>
                <th className="num">Attempts</th><th>Reconciled</th>
              </tr>
            </thead>
            <tbody>
              {uncertain.actions.map((item) => (
                <tr key={item.action_record_id} data-testid={`uncertain-${item.action_record_id}`}>
                  <td>
                    {item.action_type}
                    <div className="rules mono">{item.idempotency_key}</div>
                  </td>
                  <td>{item.target_ref}</td>
                  <td className="outcome-failed">{item.status}</td>
                  <td className="num">{item.attempt_count}</td>
                  <td>
                    {item.reconciled_by ? (
                      <>
                        {item.reconciled_by}
                        <div className="rules">{item.reconciliation_evidence}</div>
                      </>
                    ) : (
                      <Absent />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* No button, deliberately. Reconciliation is an accountable act by a named
              person, and there is no authenticated identity (ADR-0022, ADR-0025). */}
          <p className="subtitle">
            Resolving one is a human attestation with mandatory evidence. There is no
            retry control: a retry becomes possible only after somebody attests the effect
            did not occur.
          </p>
          {uncertain.actions
            .filter((item) => !item.reconciled_by)
            .map((item) => (
              <pre className="cli" key={`cmd-${item.action_record_id}`}
                   data-testid={`reconcile-command-${item.action_record_id}`}>
                {item.reconcile_command}
              </pre>
            ))}
        </Section>
      ) : null}

      {cost ? (
        <Section title="Cost" subtitle={`Six-decimal precision — ${cost.pricing_versions.join(", ") || "no entries"}.`}>
          <div className="stat-grid">
            <Stat label="Model cost" value={formatCost(cost.model_cost)} hint={`${cost.model_calls} calls`} />
            <Stat label="Tool cost" value={formatCost(cost.tool_cost)} hint={`${cost.tool_calls} calls`} />
            <Stat label="Total" value={formatCost(cost.total_cost)} />
          </div>
          <p className="caveat" data-testid="concurrency-caveat">{cost.concurrency_note}</p>
          <table>
            <thead><tr><th>Kind</th><th>Type</th><th className="num">Amount</th><th>Pricing</th></tr></thead>
            <tbody>
              {cost.ledger.map((entry, index) => (
                <tr key={`${entry.kind}-${index}`}>
                  <td>{entry.kind}</td>
                  <td>{entry.cost_type}</td>
                  <td className="num">{formatCost(entry.amount_usd)}</td>
                  <td className="mono">{entry.pricing_version}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      ) : null}

      {timeline ? (
        <Section
          title={`Timeline (${timeline.events.length} events, ${timeline.trace_count} trace)`}
          subtitle="Ordering is the API's. Missing tracing metadata is shown as absent, never invented."
        >
          <table>
            <thead>
              <tr>
                <th>When</th><th>Source</th><th>Event</th><th>Trace</th><th>Span</th><th>Parent</th><th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {timeline.events.map((event, index) => (
                <tr key={`${event.source}-${index}`}>
                  <td className="mono">{formatTimestamp(event.occurred_at)}</td>
                  <td>
                    {event.source}
                    <SimulatedBadge status={event.integration_status} />
                  </td>
                  <td className="mono">
                    {event.event_type}
                    <div className="rules">{event.detail}</div>
                  </td>
                  <td className="mono">{event.trace_id ? shortId(event.trace_id) : <Absent />}</td>
                  <td className="mono">{event.span_id ? shortId(event.span_id) : <Absent />}</td>
                  <td className="mono">{event.parent_span_id ? shortId(event.parent_span_id) : <Absent />}</td>
                  <td className="num">{event.amount_usd ? formatCost(event.amount_usd) : <Absent />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      ) : null}
    </>
  );
}
