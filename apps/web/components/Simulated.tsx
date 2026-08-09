/**
 * SIMULATED visibility -- rule 5, rendered.
 *
 * Two distinct things live here, and keeping them apart is the point:
 *
 * * `SimulatedBanner` states the *environment*. It is a constant, and it is allowed to
 *   be, because it describes the deployment rather than any particular row.
 * * `SimulatedBadge` states a *fact about one row*, and is driven entirely by data the
 *   API returned. It renders nothing when the API says nothing.
 *
 * If the row badge were also a constant, a real integration could appear one day and
 * every row would keep claiming SIMULATED -- the badge would be decoration rather than
 * evidence. So the badge takes a value and refuses to invent one.
 */

export function SimulatedBanner() {
  return (
    <div className="banner" role="status">
      <strong>SIMULATED ENVIRONMENT</strong> — every integration is fixture-backed. No
      CRM, email, or Slack system is connected, and no message has ever been sent. LLM
      responses are replayed from hand-authored fixtures; this system has never made a
      live API call.
    </div>
  );
}

/**
 * A row-level badge, driven by returned data.
 *
 * @param status  `integration_status` from the API, e.g. `"SIMULATED"`.
 * @param isSimulated  `is_simulated`, where a row carries it instead.
 * @param isReplay  `is_replay` for model activity, shown as a distinct marker.
 */
export function SimulatedBadge({
  status,
  isSimulated,
  isReplay,
}: {
  status?: string | null;
  isSimulated?: boolean | null;
  isReplay?: boolean | null;
}) {
  const labels: string[] = [];

  if (status) labels.push(status);
  else if (isSimulated) labels.push("SIMULATED");

  // Replay is a *different* claim from simulated: the adapter was fixture-backed, and
  // separately the model response was replayed rather than generated. A reader deserves
  // to see which one they are looking at.
  if (isReplay) labels.push("REPLAY");

  // Nothing returned means nothing asserted. Rendering a badge here would be inventing
  // provenance the API did not supply.
  if (labels.length === 0) return null;

  return (
    <>
      {labels.map((label) => (
        <span
          key={label}
          // A live integration is not a neutral tag on this dashboard -- it is the one
          // thing a reader must not skim past. So the modifier class is derived from the
          // label rather than fixed, and `badge-implemented` is styled as a warning.
          className={`badge badge-${label.toLowerCase()}`}
          data-testid={`badge-${label.toLowerCase()}`}
        >
          {label}
        </span>
      ))}
    </>
  );
}
