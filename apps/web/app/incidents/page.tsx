/**
 * Incident queue -- "Which incidents need attention, and in what order?"
 *
 * Ordering is the API's. The backend ranks by severity and weighted value; re-sorting
 * here would mean two different answers to "what is most urgent" depending on where you
 * looked.
 */
import Link from "next/link";
import { ErrorNote } from "@/components/Primitives";
import { SimulatedBadge } from "@/components/Simulated";
import { api, optional } from "@/lib/api";
import { formatMoney, titleCase } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function IncidentQueuePage() {
  const list = await optional(() => api.incidents());
  if (!list) return <ErrorNote message="The incidents endpoint returned no data." />;

  return (
    <>
      <h1>Incident queue</h1>
      <p className="subtitle">
        Which incidents need attention, and in what order. Ordering is the API&apos;s.
      </p>

      <table>
        <thead>
          <tr>
            <th>Incident</th>
            <th>Account</th>
            <th>Opportunity</th>
            <th>Severity</th>
            <th>Status</th>
            <th className="num">Amount</th>
            <th className="num">At risk</th>
          </tr>
        </thead>
        <tbody>
          {list.incidents.length === 0 ? (
            <tr>
              <td colSpan={7}>
                No incidents. Run <code>make demo</code> to populate the golden scenario.
              </td>
            </tr>
          ) : (
            list.incidents.map((incident) => (
              <tr key={incident.incident_ref}>
                <td>
                  <Link href={`/incidents/${incident.incident_ref}`}>
                    {incident.incident_ref}
                  </Link>
                </td>
                <td>
                  {incident.account_name}
                  {/* Driven by the row's own flag, not by the page. */}
                  <SimulatedBadge isSimulated={incident.is_simulated} />
                </td>
                <td>{incident.opportunity_ref ?? "—"}</td>
                <td>{titleCase(incident.severity)}</td>
                <td>{titleCase(incident.status)}</td>
                <td className="num">
                  {formatMoney(incident.amount, incident.currency ?? "USD")}
                </td>
                <td className="num">{formatMoney(incident.at_risk_value)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </>
  );
}
