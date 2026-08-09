/**
 * Integration catalogue — every adapter and the status it declares about itself.
 *
 * Worth a screen precisely *because* everything is SIMULATED. Both halves come out of the
 * adapter module: the status through `INTEGRATION_STATUS` — the same constant stamped
 * onto every tool result — and the "what changes when this becomes real" notes out of the
 * adapter's own docstring. Nothing on this page is UI copy about integrations; it is the
 * integrations describing themselves.
 */
import { ErrorNote, Section } from "@/components/Primitives";
import { SimulatedBadge } from "@/components/Simulated";
import { api, optional } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function IntegrationCataloguePage() {
  const catalogue = await optional(() => api.integrations());
  if (!catalogue) return <ErrorNote message="The integrations endpoint returned no data." />;

  return (
    <>
      <h1>Integration catalogue</h1>
      <p className="subtitle">
        Read from each adapter&apos;s declared <code>INTEGRATION_STATUS</code> and its own
        docstring — not from a list maintained here.
      </p>

      <div className="identity-note" data-testid="reality-note">
        {catalogue.any_real ? (
          <>
            <strong>At least one integration is no longer simulated.</strong> A real
            external system is bound. Check what it touches before demonstrating this.
          </>
        ) : (
          <>
            <strong>No production integration is connected.</strong> Nothing here is real:
            no CRM, email, or Slack system is reachable, no credential exists, and no
            message has ever been sent. Sending email is not a capability this system has
            — there is no <code>messaging_send_email</code> tool and no send method on the
            messaging port.
          </>
        )}
      </div>

      <Section title={`Adapters (${catalogue.integrations.length})`}>
        <table>
          <thead>
            <tr>
              <th>Integration</th>
              <th>Status</th>
              <th>Adapter</th>
              <th>Port</th>
            </tr>
          </thead>
          <tbody>
            {catalogue.integrations.map((item) => (
              <tr key={item.module} data-testid={`row-${item.module}`}>
                <td>
                  {item.name}
                  <div className="rules">{item.summary}</div>
                </td>
                <td>
                  <SimulatedBadge status={item.integration_status} />
                </td>
                <td className="mono">{item.module}</td>
                <td className="mono">{item.port}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section
        title="What changes when these become real"
        subtitle="Each note is a paragraph from the adapter's own docstring. If the adapter is wrong, this is wrong — which is the point."
      >
        {catalogue.integrations.map((item) => (
          <div className="card" key={`roadmap-${item.module}`}>
            <h3>
              {item.name}
              <SimulatedBadge status={item.integration_status} />
            </h3>
            {item.when_real_documented ? (
              <dl className="roadmap">
                {item.when_real.map((note) => (
                  <div key={`${item.module}-${note.heading}`}>
                    <dt>{note.heading}</dt>
                    <dd>{note.body}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              // Docstrings are stripped under `python -O`. Saying so beats substituting
              // text the adapter never wrote.
              <p className="absent" data-testid={`undocumented-${item.module}`}>
                This adapter did not return a roadmap section — docstrings appear to have
                been stripped from the running build.
              </p>
            )}
          </div>
        ))}
      </Section>
    </>
  );
}
