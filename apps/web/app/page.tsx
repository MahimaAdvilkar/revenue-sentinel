/**
 * Executive overview -- "What is at risk, in dollars, right now?"
 */
import { Section, Stat, ErrorNote } from "@/components/Primitives";
import { api, optional } from "@/lib/api";
import { formatCost, formatMoney, titleCase } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const overview = await optional(() => api.overview());
  const approvals = await optional(() => api.approvals());
  const cost = await optional(() => api.cost("INC-001"));

  if (!overview) {
    return <ErrorNote message="The overview endpoint returned no data." />;
  }

  const byStatus = Object.entries(overview.incidents_by_status);

  return (
    <>
      <h1>Executive overview</h1>
      <p className="subtitle">What is at risk, in dollars, right now.</p>

      <div className="stat-grid">
        <Stat
          label="Pipeline at risk"
          value={formatMoney(overview.total_at_risk)}
          hint="Deterministic — computed by analytics/, never by a model"
        />
        <Stat label="Weighted pipeline" value={formatMoney(overview.total_weighted)} />
        <Stat label="Open incidents" value={String(overview.open_incidents)} />
        <Stat
          label="Awaiting approval"
          value={String(approvals?.pending.length ?? 0)}
          hint="Decided on the CLI — see Approvals"
        />
        <Stat
          label="Total spend"
          value={formatCost(cost?.total_cost ?? "0.000000")}
          hint="Fixture mode consumes no tokens"
        />
      </div>

      <Section
        title="Incidents by status"
        subtitle={`Environment reports ${overview.integration_status} for all integrations.`}
      >
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th className="num">Count</th>
            </tr>
          </thead>
          <tbody>
            {byStatus.length === 0 ? (
              <tr>
                <td colSpan={2}>No incidents yet — run <code>make demo</code>.</td>
              </tr>
            ) : (
              byStatus.map(([status, count]) => (
                <tr key={status}>
                  <td>{titleCase(status)}</td>
                  <td className="num">{count}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Section>
    </>
  );
}
