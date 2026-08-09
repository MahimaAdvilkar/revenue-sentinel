/** Small presentational pieces shared across screens. */
import Link from "next/link";
import { NOT_RECORDED } from "@/lib/format";

export function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint ? <div className="stat-hint">{hint}</div> : null}
    </div>
  );
}

export function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="section">
      <h2>{title}</h2>
      {subtitle ? <p className="subtitle">{subtitle}</p> : null}
      {children}
    </section>
  );
}

/** A value the API did not supply. Never a placeholder that could be mistaken for one. */
export function Absent() {
  return <span className="absent">{NOT_RECORDED}</span>;
}

export function Decision({ decision }: { decision: string | null | undefined }) {
  if (!decision) return <Absent />;
  return <span className={`decision decision-${decision}`}>{decision.replace(/_/g, " ")}</span>;
}

export function Nav() {
  return (
    <nav className="nav">
      <Link href="/">Overview</Link>
      <Link href="/incidents">Incidents</Link>
      <Link href="/approvals">Approvals</Link>
      <Link href="/cost">Cost</Link>
      <Link href="/evaluation">Evaluation</Link>
      <Link href="/integrations">Integrations</Link>
    </nav>
  );
}

/**
 * A figure that has never been measured.
 *
 * `observed: false` means no data exists, not that the value is zero -- and the two must
 * not look the same on a screen. Rendering a cache hit rate of `0%` would read as
 * "caching works badly" rather than "caching has never run".
 */
export function NeverObserved({ note }: { note: string }) {
  return (
    <div className="never-observed" data-testid="never-observed">
      <strong>never observed</strong>
      <div className="hint">{note}</div>
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="error-note">
      <strong>Could not load.</strong> {message}
      <div className="hint">
        Is the API running? <code>make api</code> — then <code>make demo</code> to
        populate the golden scenario.
      </div>
    </div>
  );
}
