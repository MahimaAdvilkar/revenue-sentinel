/**
 * Evaluation centre — every attempt, most recently recorded first.
 *
 * **A list, not a status.** ADR-0021 made evaluation attempts append-only precisely so a
 * later passing run cannot erase the evidence that an earlier one failed. A screen
 * showing only the latest result would undo that in the presentation layer, which is
 * where it would be hardest to notice — so nothing here is labelled "current".
 *
 * The detail panel is the *most recent attempt*, and says so. `/evaluation/latest` is the
 * only endpoint that returns per-check detail; the history endpoint returns summaries, so
 * an older attempt can be seen in the list but not expanded. That limit is stated on the
 * screen rather than hidden behind a control that would do nothing.
 */
import { ErrorNote, Section, Stat } from "@/components/Primitives";
import { api, optional } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function EvaluationCentrePage() {
  const [history, latest] = await Promise.all([
    optional(() => api.evaluationHistory()),
    optional(() => api.evaluation()),
  ]);

  if (!history) return <ErrorNote message="The evaluation endpoint returned no data." />;

  const newest = history.runs[0];
  const failures = latest?.results.filter((result) => result.outcome !== "passed") ?? [];

  return (
    <>
      <h1>Evaluation centre</h1>
      <p className="subtitle">
        Deterministic and structural. Every check is decided from persisted rows — no
        model is consulted, by a check or by the reporter.
      </p>

      <div className="stat-grid">
        <Stat
          label="Attempts recorded"
          value={String(history.runs.length)}
          hint="Append-only — a failure is never overwritten by a later pass"
        />
        <Stat
          label="Most recent attempt"
          value={newest ? `${newest.passed}/${newest.total}` : "—"}
          hint={newest ? `#${newest.sequence}, ${formatTimestamp(newest.started_at)}` : undefined}
        />
        <Stat
          label="LLM judge"
          value={history.llm_judge_used ? "USED" : "NOT USED"}
          hint="A hand-authored judge fixture would be circular (ADR-0021)"
        />
        <Stat label="Evaluation cost" value={`$${history.evaluation_cost}`} />
      </div>

      <Section
        title="History"
        subtitle="Ordered by insertion sequence, newest first. Attempts of the golden run share a frozen timestamp, so the sequence — not the clock — is what orders them."
      >
        <table>
          <thead>
            <tr>
              <th className="num">#</th>
              <th>Started</th>
              <th>Suite</th>
              <th>Evaluator</th>
              <th className="num">Result</th>
              <th>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {history.runs.length === 0 ? (
              <tr>
                <td colSpan={6}>
                  No evaluation has been recorded. Run <code>make eval</code>.
                </td>
              </tr>
            ) : (
              history.runs.map((run) => (
                <tr key={run.evaluation_run_id}>
                  <td className="num">{run.sequence}</td>
                  <td className="mono">{formatTimestamp(run.started_at)}</td>
                  <td>{run.suite_name}</td>
                  <td className="mono">{run.evaluator_version}</td>
                  <td className="num">
                    {run.passed}/{run.total}
                  </td>
                  <td
                    className={`outcome-${run.outcome}`}
                    data-testid={`outcome-${run.evaluation_run_id}`}
                  >
                    {run.outcome}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Section>

      {latest ? (
        <Section
          title={`Most recent attempt — ${latest.passed}/${latest.total}`}
          subtitle="Every check, with what it expected and what it found."
        >
          <p className="caveat" data-testid="detail-scope">
            These are the checks of the most recent attempt only — not a verdict on the
            system. Earlier attempts stay in the history above; per-check detail is
            retained for the latest attempt alone.
          </p>
          {failures.length > 0 ? (
            <p className="caveat">{failures.length} check(s) failing.</p>
          ) : null}
          <table>
            <thead>
              <tr>
                <th>Check</th>
                <th>Outcome</th>
                <th>Expected</th>
                <th>Actual</th>
              </tr>
            </thead>
            <tbody>
              {latest.results.map((result) => (
                <tr key={result.check_name}>
                  <td className="mono">{result.check_name}</td>
                  <td className={`outcome-${result.outcome}`}>{result.outcome}</td>
                  <td className="rules">{result.expected}</td>
                  <td className="rules">{result.actual}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      ) : null}
    </>
  );
}
