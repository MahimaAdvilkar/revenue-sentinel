/**
 * The generated OpenAPI contract (ADR-0023).
 *
 * These assertions are about the *schema the frontend was built against*, not about a
 * running server. If the backend adds an approval mutation, regenerating produces a
 * schema that fails here -- so the read-only boundary is enforced on both sides of the
 * wire rather than only in pytest.
 */
import { describe, expect, it } from "vitest";
import schema from "@/generated/openapi.json";

const paths = schema.paths as Record<string, Record<string, unknown>>;

describe("generated OpenAPI contract", () => {
  it("exposes no approval mutation route", () => {
    // ADR-0018 + ADR-0022. The CLI is the only mutation surface.
    const approvalMutations = Object.entries(paths).flatMap(([path, ops]) =>
      Object.keys(ops)
        .filter((method) => ["post", "put", "patch", "delete"].includes(method))
        .filter(() => path.includes("approval"))
        .map((method) => `${method.toUpperCase()} ${path}`),
    );
    expect(approvalMutations).toEqual([]);
  });

  it("exposes no mutation route at all outside ingestion", () => {
    const mutations = Object.entries(paths).flatMap(([path, ops]) =>
      Object.keys(ops)
        .filter((method) => ["post", "put", "patch", "delete"].includes(method))
        .filter(() => path !== "/ingest")
        .map((method) => `${method.toUpperCase()} ${path}`),
    );
    expect(mutations).toEqual([]);
  });

  it("publishes every endpoint the client layer calls", () => {
    // A typo or a removed endpoint becomes a failing test rather than a 404 in the UI.
    for (const path of [
      "/overview",
      "/incidents",
      "/incidents/{incident_ref}",
      "/incidents/{incident_ref}/investigation",
      "/incidents/{incident_ref}/interventions",
      "/incidents/{incident_ref}/timeline",
      "/incidents/{incident_ref}/cost",
      "/approvals",
      "/incidents/{incident_ref}/uncertain-actions",
      "/cost",
      "/evaluation/latest",
      "/evaluation/runs",
      "/integrations",
    ]) {
      expect(paths[path], `${path} missing from the schema`).toBeDefined();
      expect(paths[path]?.get, `${path} should be a GET`).toBeDefined();
    }
  });

  it("exposes no way to reconcile an uncertain action over HTTP", () => {
    // ADR-0025: reconciliation is an accountable human act with mandatory evidence, and
    // there is no authenticated identity. The CLI is the only mutation surface, so the
    // generated contract must offer nothing that looks like a reconcile button's backend.
    const reconciliationMutations = Object.entries(paths).flatMap(([path, ops]) =>
      Object.keys(ops)
        .filter((method) => ["post", "put", "patch", "delete"].includes(method))
        .filter(() => /reconcile|uncertain|action/i.test(path))
        .map((method) => `${method.toUpperCase()} ${path}`),
    );
    expect(reconciliationMutations).toEqual([]);
    expect(paths["/incidents/{incident_ref}/uncertain-actions"]?.get).toBeDefined();
  });

  it("serialises money and cost as strings, not numbers", () => {
    // A JSON number is an IEEE float and cannot carry a Decimal. This is the schema-level
    // guarantee behind the six-decimal formatter.
    const components = schema.components as {
      schemas: Record<string, { properties?: Record<string, { type?: string }> }>;
    };
    const cost = components.schemas.CostSummaryResponse?.properties;
    expect(cost?.total_cost?.type).toBe("string");
    expect(cost?.model_cost?.type).toBe("string");

    const impact = components.schemas.ImpactView?.properties;
    expect(impact?.at_risk_value?.type).toBe("string");

    const centre = components.schemas.CostCentreResponse?.properties;
    expect(centre?.total_cost?.type).toBe("string");

    const budget = components.schemas.BudgetView?.properties;
    expect(budget?.limit_usd?.type).toBe("string");
    expect(budget?.remaining_usd?.type).toBe("string");
  });

  it("models an unobserved metric as nullable with a note, not as a number", () => {
    // The schema itself has to make "never measured" representable. If `value` were a
    // required number, the API would have no way to say anything other than a rate --
    // and 0 is the only value it could send.
    const components = schema.components as {
      schemas: Record<
        string,
        { required?: string[]; properties?: Record<string, { anyOf?: { type?: string }[] }> }
      >;
    };
    const metric = components.schemas.ObservedMetric;
    expect(metric?.required).toEqual(expect.arrayContaining(["observed", "value", "note"]));
    const valueTypes = metric?.properties?.value?.anyOf?.map((entry) => entry.type) ?? [];
    expect(valueTypes).toContain("null");
  });

  it("declares tracing identifiers as nullable rather than required", () => {
    // Absent metadata must be representable, or the API would have to invent it.
    const components = schema.components as {
      schemas: Record<string, { required?: string[] }>;
    };
    const required = components.schemas.TimelineEventView?.required ?? [];
    // They are present-but-nullable: the field always appears, its value may be null.
    expect(required).toContain("trace_id");
    const event = (components.schemas.TimelineEventView as unknown as {
      properties: Record<string, { anyOf?: { type?: string }[] }>;
    }).properties;
    const traceTypes = event.trace_id?.anyOf?.map((entry) => entry.type) ?? [];
    expect(traceTypes).toContain("null");
  });
});
