/**
 * Approval inbox -- "What is waiting on a person?"
 *
 * **Read-only, by decision** (ADR-0022). There is no Approve button and no mutation
 * endpoint behind one. Approvals are a *claimed* identity with no authentication
 * (ADR-0018), and a button would imply a session, a user, and an accountable
 * `decided_by` that do not exist -- while being reachable by anything that can route to
 * the service. The screen shows the exact command instead, which is honest about who is
 * running it.
 */
import { ErrorNote, Section } from "@/components/Primitives";
import { SimulatedBadge } from "@/components/Simulated";
import { api, optional } from "@/lib/api";
import { formatTimestamp, titleCase } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ApprovalsPage() {
  const inbox = await optional(() => api.approvals());
  if (!inbox) return <ErrorNote message="The approvals endpoint returned no data." />;

  return (
    <>
      <h1>Approval inbox</h1>
      <p className="subtitle">What is waiting on a person.</p>

      <div className="identity-note" data-testid="identity-note">
        {inbox.identity_note}
        <div style={{ marginTop: "0.5rem" }}>
          This dashboard is <strong>read-only</strong>. Approving and rejecting happen on
          the command line, where it is clear that the action runs as whoever holds the
          shell rather than as a verified user (ADR-0022).
        </div>
      </div>

      <Section title={`Pending (${inbox.pending.length})`}>
        {inbox.pending.length === 0 ? (
          <p className="subtitle">Nothing is waiting on a person.</p>
        ) : (
          inbox.pending.map((item) => (
            <div className="card" key={item.approval_ref}>
              <div>
                <strong>{item.approval_ref}</strong> — {item.intervention_title}
                <SimulatedBadge status={item.integration_status} />
              </div>
              <div className="rules">
                status {titleCase(item.status)} · requested by{" "}
                <span className="mono">{item.requested_by}</span> · expires{" "}
                {formatTimestamp(item.expires_at)}
              </div>
              <div className="cli">
                <code data-testid={`approve-command-${item.approval_ref}`}>
                  {item.approve_command}
                </code>
              </div>
            </div>
          ))
        )}
      </Section>
    </>
  );
}
