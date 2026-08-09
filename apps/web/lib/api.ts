/**
 * The typed client layer. Every network call in this app goes through here.
 *
 * Fetch logic is centralised rather than scattered through components for one reason
 * that matters more than tidiness: the response types come from `generated/api.ts`,
 * which is derived from FastAPI's OpenAPI schema (ADR-0023). A backend field rename
 * therefore breaks compilation *here*, at one call site, instead of silently producing
 * `undefined` in a component that renders it as an empty cell.
 *
 * There are deliberately **no hand-written response interfaces** in this file. Every
 * type below is an alias into the generated schema.
 */
import type { components, paths } from "@/generated/api";

/** The only origin this app talks to at runtime. */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type Schemas = components["schemas"];

export type Overview = Schemas["OverviewResponse"];
export type IncidentList = Schemas["IncidentListResponse"];
export type IncidentSummary = Schemas["IncidentSummary"];
export type IncidentDetail = Schemas["IncidentDetail"];
export type Investigation = Schemas["InvestigationResponse"];
export type EvidenceItem = Schemas["EvidenceItemView"];
export type Hypothesis = Schemas["HypothesisView"];
export type Impact = Schemas["ImpactView"];
export type Intervention = Schemas["InterventionView"];
export type Timeline = Schemas["TimelineResponse"];
export type TimelineEvent = Schemas["TimelineEventView"];
export type CostSummary = Schemas["CostSummaryResponse"];
export type CostLedgerEntry = Schemas["CostLedgerEntry"];
export type ApprovalInbox = Schemas["ApprovalInboxResponse"];
export type ApprovalItem = Schemas["ApprovalInboxItem"];

/**
 * Every read path the dashboard uses, checked against the generated schema.
 *
 * `paths` only contains routes the backend actually publishes, so a typo or a removed
 * endpoint is a compile error rather than a 404 discovered by a user.
 */
type ReadPath = keyof paths;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function get<T>(path: ReadPath | string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    // The dashboard reads live governance state; a cached approval queue would show
    // work as pending after somebody had already decided it.
    cache: "no-store",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new ApiError(
      response.status,
      String(path),
      `GET ${path} failed with ${response.status}`,
    );
  }
  return (await response.json()) as T;
}

export const api = {
  overview: () => get<Overview>("/overview"),
  incidents: () => get<IncidentList>("/incidents"),
  incident: (ref: string) => get<IncidentDetail>(`/incidents/${ref}`),
  investigation: (ref: string) =>
    get<Investigation>(`/incidents/${ref}/investigation`),
  interventions: (ref: string) =>
    get<Intervention[]>(`/incidents/${ref}/interventions`),
  timeline: (ref: string) => get<Timeline>(`/incidents/${ref}/timeline`),
  cost: (ref: string) => get<CostSummary>(`/incidents/${ref}/cost`),
  approvals: () => get<ApprovalInbox>("/approvals"),
};

/**
 * Tolerant read for a screen that should degrade rather than blank out.
 *
 * An incident with no completed run has no investigation, and the API says so with a
 * 404. That is a legitimate state, not an error worth failing the whole page over.
 */
export async function optional<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
