/**
 * Cost centre — spend across every run, against every configured budget.
 *
 * Two panels here deliberately refuse to show a number. Cache effectiveness and the
 * replay share of the model mix have never been measured, because no live API call has
 * ever been made. A `0%` cache hit rate rendered as a metric is the single most
 * misreadable thing this dashboard could display.
 */
import { ErrorNote, NeverObserved, Section, Stat } from "@/components/Primitives";
import { api, optional } from "@/lib/api";
import { formatCost } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function CostCentrePage() {
  const cost = await optional(() => api.costCentre());
  if (!cost) return <ErrorNote message="The cost endpoint returned no data." />;

  return (
    <>
      <h1>Cost centre</h1>
      <p className="subtitle">
        Every figure at six decimals. Priced from real token counts — fixture mode
        consumes none, so the totals are true rather than rounded.
      </p>

      <div className="stat-grid">
        <Stat label="Total spend" value={formatCost(cost.total_cost)} />
        <Stat label="Model" value={formatCost(cost.model_cost)} hint={`${cost.model_calls} calls`} />
        <Stat label="Tools" value={formatCost(cost.tool_cost)} hint={`${cost.tool_calls} calls — SIMULATED adapters bill nothing`} />
        <Stat label="Pricing" value={cost.pricing_versions.join(", ") || "—"} />
      </div>

      <Section title="Budgets">
        {cost.budgets.length === 0 ? (
          <p className="subtitle">
            None configured. A missing budget means <em>unbudgeted</em>, not a limit of
            zero — budgets are opt-in.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Scope</th><th className="num">Limit</th><th className="num">Consumed</th>
                <th className="num">Remaining</th><th>Enforcement</th>
              </tr>
            </thead>
            <tbody>
              {cost.budgets.map((budget, index) => (
                <tr key={`${budget.scope}-${index}`}>
                  <td>{budget.scope}{budget.scope_ref ? <span className="rules"> {budget.scope_ref}</span> : null}</td>
                  <td className="num">{formatCost(budget.limit_usd)}</td>
                  <td className="num">{formatCost(budget.consumed_usd)}</td>
                  <td className="num">{formatCost(budget.remaining_usd)}</td>
                  <td>{budget.hard_stop ? "hard stop" : "soft — logs and continues"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="caveat" data-testid="concurrency-caveat">{cost.concurrency_note}</p>
      </Section>

      <Section title="Spend by incident">
        <table>
          <thead>
            <tr>
              <th>Incident</th><th className="num">Model</th><th className="num">Tools</th>
              <th className="num">Total</th><th className="num">Calls</th>
            </tr>
          </thead>
          <tbody>
            {cost.by_incident.map((row) => (
              <tr key={row.incident_ref}>
                <td>{row.incident_ref}</td>
                <td className="num">{formatCost(row.model_cost)}</td>
                <td className="num">{formatCost(row.tool_cost)}</td>
                <td className="num">{formatCost(row.total_cost)}</td>
                <td className="num">{row.model_calls} / {row.tool_calls}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section
        title="Model mix"
        subtitle="Routing is deterministic, so this reports which models ran — not a comparison between them."
      >
        <table>
          <thead>
            <tr><th>Model</th><th className="num">Calls</th><th className="num">Replayed</th><th className="num">Cost</th></tr>
          </thead>
          <tbody>
            {cost.model_mix.map((entry) => (
              <tr key={entry.model_id}>
                <td className="mono">{entry.model_id}</td>
                <td className="num">{entry.calls}</td>
                <td className="num" data-testid={`replayed-${entry.model_id}`}>
                  {entry.replayed} of {entry.calls}
                </td>
                <td className="num">{formatCost(entry.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {cost.model_mix.every((entry) => entry.replayed === entry.calls) ? (
          <p className="caveat">
            Every call was replayed from a fixture. This is a record of what ran, not a
            measurement of live model behaviour.
          </p>
        ) : null}
      </Section>

      <Section title="Cache effectiveness">
        {cost.cache_effectiveness.observed ? (
          <Stat label="Cache hit rate" value={cost.cache_effectiveness.value ?? "—"} hint={cost.cache_effectiveness.note} />
        ) : (
          <NeverObserved note={cost.cache_effectiveness.note} />
        )}
      </Section>
    </>
  );
}
