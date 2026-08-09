/**
 * The four screens, rendered against golden-run data shapes.
 *
 * These assert *behaviour and contract*, not markup: no snapshots, no pixel checks. What
 * is pinned is the handful of properties that would be quietly wrong if someone
 * refactored -- ordering, precision, absence, and the missing button.
 *
 * Server components are async, so each is awaited and its element tree rendered.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as fixtures from "./fixtures/golden";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    optional: async (load: () => Promise<unknown>) => load(),
    api: {
      overview: async () => fixtures.overview,
      incidents: async () => ({ incidents: [], total: 0 }),
      incident: async () => ({}),
      investigation: async () => fixtures.investigation,
      interventions: async () => fixtures.interventions,
      timeline: async () => fixtures.timeline,
      cost: async () => fixtures.cost,
      approvals: async () => fixtures.approvals,
    },
  };
});

afterEach(cleanup);

describe("executive overview", () => {
  it("answers what is at risk, in dollars", async () => {
    const Page = (await import("@/app/page")).default;
    render(await Page());

    expect(screen.getByText("$32,130.00 USD")).toBeTruthy();
    expect(screen.getByText("$108,000.00 USD")).toBeTruthy();
  });

  it("shows total spend at six decimals", async () => {
    const Page = (await import("@/app/page")).default;
    render(await Page());

    expect(screen.getByText("$0.000000")).toBeTruthy();
    expect(screen.queryByText("$0.00")).toBeNull();
  });
});

describe("approval inbox", () => {
  it("renders the exact CLI command", async () => {
    const Page = (await import("@/app/approvals/page")).default;
    render(await Page());

    expect(
      screen.getByTestId("approve-command-APR-001").textContent,
    ).toBe("uv run rs approve APR-001 --as usr:your-name");
  });

  it("states that identity is not authenticated", async () => {
    const Page = (await import("@/app/approvals/page")).default;
    render(await Page());

    const note = screen.getByTestId("identity-note").textContent ?? "";
    expect(note).toContain("CLAIMED identity");
    expect(note).toContain("no authentication");
    expect(note).toContain("read-only");
  });

  it("offers no approve or reject control", async () => {
    // ADR-0022, asserted rather than assumed: a button here would imply a session and an
    // accountable user that do not exist.
    const Page = (await import("@/app/approvals/page")).default;
    const { container } = render(await Page());

    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(container.querySelectorAll("form")).toHaveLength(0);
    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /approve|reject/i })).toBeNull();
  });
});

describe("incident detail", () => {
  async function renderDetail() {
    const Page = (await import("@/app/incidents/[ref]/page")).default;
    const api = await import("@/lib/api");
    vi.spyOn(api.api, "incident").mockResolvedValue({
      incident_ref: "INC-001",
      title: "Stalled opportunity",
      status: "completed",
      severity: "high",
      account: { account_ref: "ACC-1001", name: "Northwind Logistics", is_simulated: true },
      opportunity: { opportunity_ref: "OPP-2001" },
    } as never);
    return render(await Page({ params: Promise.resolve({ ref: "INC-001" }) }));
  }

  it("preserves the API's timeline ordering rather than re-sorting", async () => {
    const { container } = await renderDetail();

    const rows = container.querySelectorAll("table tbody tr");
    const timelineRows = Array.from(rows).filter((row) =>
      /audit_event|model_call|cost_entry/.test(row.textContent ?? ""),
    );
    const order = timelineRows.map((row) => {
      const text = row.textContent ?? "";
      if (text.includes("audit_event")) return "audit_event";
      if (text.includes("model_call")) return "model_call";
      return "cost_entry";
    });

    // Exactly the order the fixture (and therefore the API) supplied.
    expect(order).toEqual(["audit_event", "model_call", "cost_entry"]);
  });

  it("renders absent trace and span ids as 'not recorded'", async () => {
    const { container } = await renderDetail();

    const auditRow = Array.from(container.querySelectorAll("tbody tr")).find((row) =>
      (row.textContent ?? "").includes("incident.opened"),
    );
    expect(auditRow).toBeTruthy();
    expect(within(auditRow as HTMLElement).getAllByText("not recorded").length).toBeGreaterThan(0);
  });

  it("shows the concurrency caveat beside cost", async () => {
    await renderDetail();

    const caveat = screen.getByTestId("concurrency-caveat").textContent ?? "";
    expect(caveat).toContain("ADR-0019");
    expect(caveat).toContain("can race");
  });

  it("shows cost at six decimals", async () => {
    await renderDetail();
    expect(screen.getAllByText("$0.000000").length).toBeGreaterThan(0);
  });

  it("badges evidence from the returned integration_status", async () => {
    await renderDetail();
    expect(screen.getAllByTestId("badge-simulated").length).toBeGreaterThan(0);
  });
});
