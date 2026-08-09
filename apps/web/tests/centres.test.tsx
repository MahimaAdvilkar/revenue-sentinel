/**
 * The three Session 10 centres.
 *
 * Each of these screens carries one claim that is easy to break by accident and hard to
 * notice once broken, so each has a test that would fail loudly:
 *
 * * **Cost** — an unmeasured cache must never render as a percentage. `0%` reads as
 *   "caching works badly"; the truth is that nothing has ever been measured.
 * * **Evaluation** — the history is a list, and a failed attempt has to stay visible
 *   after a later pass. A screen showing only the newest row would undo ADR-0021 in the
 *   presentation layer, which is where it would be hardest to spot.
 * * **Integrations** — the catalogue must show what the adapters declare, not a
 *   hand-maintained list, and must state plainly that nothing is real.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as fixtures from "./fixtures/golden";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    optional: async (load: () => Promise<unknown>) => load(),
    api: {
      costCentre: async () => fixtures.costCentre,
      evaluationHistory: async () => fixtures.evaluationHistory,
      evaluation: async () => fixtures.evaluationLatest,
      integrations: async () => fixtures.integrations,
    },
  };
});

afterEach(cleanup);

async function renderPage(path: string) {
  const Page = (await import(path)).default;
  return render(await Page());
}

describe("cost centre", () => {
  it("reports cache effectiveness as never observed, not as a rate", async () => {
    const { container } = await renderPage("@/app/cost/page");

    const text = container.textContent ?? "";
    expect(text).toContain("Never observed");
    expect(text).toContain("absence of data, not a hit rate of zero");
    // The specific mistake this guards against: a percentage, any percentage.
    expect(text).not.toMatch(/\d+(\.\d+)?%/);
  });

  it("keeps money at six decimals everywhere", async () => {
    const { container } = await renderPage("@/app/cost/page");

    expect(screen.getByText("$24.999850")).toBeTruthy();
    expect(screen.getByText("$25.000000")).toBeTruthy();
    // A budget rendered at cent precision would hide the microdollar headroom that
    // admission control actually enforces (ADR-0019/0020).
    expect(container.textContent).not.toContain("$25.00 ");
  });

  it("says every model call was replayed rather than presenting a routing mix", async () => {
    await renderPage("@/app/cost/page");

    expect(screen.getByTestId("replayed-claude-sonnet-5").textContent).toBe("4 of 4");
    expect(screen.getByText(/record of what ran, not a measurement/)).toBeTruthy();
  });

  it("splits per-incident spend by cost type", async () => {
    const { container } = await renderPage("@/app/cost/page");

    const row = Array.from(container.querySelectorAll("tbody tr")).find((candidate) =>
      (candidate.textContent ?? "").includes("INC-001"),
    );
    expect(row).toBeTruthy();
    // Model and tool as separate columns, plus the call counts behind them.
    expect(row?.querySelectorAll("td")).toHaveLength(5);
    expect(row?.textContent).toContain("4 / 9");
  });

  it("carries the budget concurrency caveat", async () => {
    await renderPage("@/app/cost/page");

    const caveat = screen.getByTestId("concurrency-caveat").textContent ?? "";
    expect(caveat).toContain("not atomic");
    expect(caveat).toContain("ADR-0019");
  });

  it("introduces no control that could spend or change a budget", async () => {
    const { container } = await renderPage("@/app/cost/page");

    expect(container.querySelectorAll("button, form, input, select")).toHaveLength(0);
  });
});

describe("evaluation centre", () => {
  it("keeps a failed attempt visible after a later pass", async () => {
    await renderPage("@/app/evaluation/page");

    expect(
      screen.getByTestId("outcome-22222222-2222-2222-2222-222222222222").textContent,
    ).toBe("failed");
    expect(
      screen.getByTestId("outcome-11111111-1111-1111-1111-111111111111").textContent,
    ).toBe("passed");
  });

  it("renders history newest first, in the order the API returned", async () => {
    const { container } = await renderPage("@/app/evaluation/page");

    const outcomes = Array.from(container.querySelectorAll("[data-testid^='outcome-']")).map(
      (node) => node.textContent,
    );
    expect(outcomes).toEqual(["passed", "failed"]);
  });

  it("orders by insertion sequence, which is what survives a frozen timestamp", async () => {
    const { container } = await renderPage("@/app/evaluation/page");

    // Both fixture attempts share EVALUATION_TIMESTAMP -- the tie that makes clock
    // ordering arbitrary. The sequence column is what makes the list reproducible.
    const started = fixtures.evaluationHistory.runs.map((run) => run.started_at);
    expect(new Set(started).size).toBe(1);

    const sequences = Array.from(container.querySelectorAll("tbody tr"))
      .map((row) => row.querySelector("td.num")?.textContent)
      .filter(Boolean);
    expect(sequences).toEqual(["2", "1"]);
  });

  it("never presents the latest attempt as the current truth", async () => {
    const { container } = await renderPage("@/app/evaluation/page");

    const text = container.textContent ?? "";
    expect(text).not.toMatch(/current (status|truth|result)/i);
    expect(screen.getByTestId("detail-scope").textContent).toContain(
      "not a verdict on the system",
    );
  });

  it("states that per-check detail exists only for the latest attempt", async () => {
    // The history endpoint returns summaries. Saying so beats a row control that would
    // look clickable and do nothing.
    const { container } = await renderPage("@/app/evaluation/page");

    expect(screen.getByTestId("detail-scope").textContent).toContain(
      "retained for the latest attempt alone",
    );
    expect(container.querySelectorAll("button, form, input, select")).toHaveLength(0);
  });

  it("states that no LLM judge was used", async () => {
    const { container } = await renderPage("@/app/evaluation/page");

    expect(screen.getByText("NOT USED")).toBeTruthy();
    expect(container.textContent).toContain("ADR-0021");
  });
});

describe("integration catalogue", () => {
  it("badges every adapter from the status the API returned", async () => {
    await renderPage("@/app/integrations/page");

    // Two entries, each badged twice (table row and roadmap card) -- and every badge
    // driven by `integration_status`, never by a constant in the component.
    const simulated = screen.getAllByTestId("badge-simulated");
    expect(simulated).toHaveLength(fixtures.integrations.integrations.length * 2);
    expect(screen.queryByTestId("badge-implemented")).toBeNull();
  });

  it("says plainly that no production integration is connected", async () => {
    await renderPage("@/app/integrations/page");

    const note = screen.getByTestId("reality-note").textContent ?? "";
    expect(note).toContain("No production integration is connected");
    expect(note).toContain("no message has ever been sent");
    expect(note).toContain("messaging_send_email");
  });

  it("shows the adapter's own roadmap copy, not copy written in the UI", async () => {
    const { container } = await renderPage("@/app/integrations/page");

    const text = container.textContent ?? "";
    for (const note of fixtures.integrations.integrations.flatMap((item) => item.when_real)) {
      expect(text).toContain(note.heading);
      expect(text).toContain(note.body);
    }
  });

  it("says an adapter is undocumented rather than substituting copy", async () => {
    const api = await import("@/lib/api");
    const [crm] = fixtures.integrations.integrations;
    vi.spyOn(api.api, "integrations").mockResolvedValue({
      integrations: [{ ...crm!, when_real: [], when_real_documented: false }],
      any_real: false,
    });

    await renderPage("@/app/integrations/page");

    expect(
      screen.getByTestId("undocumented-integrations/simulated/crm.py").textContent,
    ).toContain("did not return a roadmap section");
  });

  it("renders a real integration differently, and changes the headline note", async () => {
    // The case nobody can test by waiting: an adapter stops being simulated. SIMULATED
    // and IMPLEMENTED must not be the same badge with different text -- a reader skimming
    // must see the difference before reading it.
    const api = await import("@/lib/api");
    vi.spyOn(api.api, "integrations").mockResolvedValue(fixtures.integrationsWithOneReal);

    await renderPage("@/app/integrations/page");

    const real = screen.getAllByTestId("badge-implemented");
    const simulated = screen.getAllByTestId("badge-simulated");
    expect(real.length).toBeGreaterThan(0);
    expect(simulated.length).toBeGreaterThan(0);
    expect(real[0]!.className).not.toBe(simulated[0]!.className);
    expect(real[0]!.className).toContain("badge-implemented");
    expect(real[0]!.textContent).toBe("IMPLEMENTED");

    const note = screen.getByTestId("reality-note").textContent ?? "";
    expect(note).toContain("no longer simulated");
    expect(note).not.toContain("No production integration is connected");
  });

  it("offers no control that could change an integration", async () => {
    // ADR-0022 again: the catalogue reports, it does not configure.
    const { container } = await renderPage("@/app/integrations/page");

    expect(container.querySelectorAll("button, form, input, select")).toHaveLength(0);
  });
});
