/**
 * Display formatting. The rules here are load-bearing, not cosmetic.
 *
 * The backend serialises money and cost as **strings** because JSON numbers are IEEE
 * floats and cannot carry a `Decimal` faithfully. Parsing those strings into JavaScript
 * numbers here would reintroduce exactly the loss the backend went to the trouble of
 * avoiding -- and would render `$0.000000` as `$0`, undoing migration 0007 in the last
 * inch of the pipeline.
 *
 * So these functions operate on strings and never call `parseFloat` on a monetary value.
 */

/** Digit grouping only. The decimal portion is passed through untouched. */
function groupThousands(whole: string): string {
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * Pipeline money: two decimals, as the backend already emits (`"108000.00"`).
 */
export function formatMoney(value: string | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined || value === "") return "—";
  const [whole = "0", fraction] = value.split(".");
  const sign = whole.startsWith("-") ? "-" : "";
  const digits = sign ? whole.slice(1) : whole;
  const body = `${groupThousands(digits)}${fraction ? `.${fraction}` : ""}`;
  return `${sign}$${body} ${currency}`.trim();
}

/**
 * Cost: **six decimals, always**, padded rather than trimmed.
 *
 * `$0.00` would hide real sub-cent spend, which is the entire reason
 * `cost_entries.amount_usd` is `NUMERIC(12, 6)`. `$0.000000` is a true figure and must
 * survive to the screen looking like one.
 */
export function formatCost(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const [whole = "0", fraction = ""] = value.split(".");
  return `$${groupThousands(whole)}.${fraction.padEnd(6, "0").slice(0, 6)}`;
}

/** A decimal string as a percentage, for confidence values like `"0.7200"`. */
export function formatConfidence(value: string): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${Math.round(parsed * 100)}%` : value;
}

/**
 * Tracing identifiers. **Absent means absent.**
 *
 * `audit_events` carry no trace or span, and the API returns `null` rather than
 * inventing one. Rendering a placeholder that looked like an ID would undo that
 * honesty, so this is explicit text a reader cannot mistake for a value.
 */
export const NOT_RECORDED = "not recorded";

export function formatTraceId(value: string | null | undefined): string {
  return value ? value : NOT_RECORDED;
}

/** Short form for dense tables; still never fabricates. */
export function shortId(value: string | null | undefined, length = 12): string {
  if (!value) return NOT_RECORDED;
  return value.length <= length ? value : `${value.slice(0, length)}…`;
}

export function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().replace("T", " ").replace("Z", " UTC");
}

export function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
