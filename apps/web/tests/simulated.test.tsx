/**
 * SIMULATED rendering.
 *
 * The distinction under test: the banner describes the environment and may be constant;
 * the row badge describes one row and must come from returned data. If the badge were
 * also constant, a real integration could land and every row would keep claiming
 * SIMULATED -- decoration rather than evidence.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SimulatedBadge, SimulatedBanner } from "@/components/Simulated";

afterEach(cleanup);

describe("SimulatedBadge", () => {
  it("renders from integration_status returned by the API", () => {
    render(<SimulatedBadge status="SIMULATED" />);
    expect(screen.getByTestId("badge-simulated").textContent).toContain("SIMULATED");
  });

  it("renders from is_simulated when a row carries that instead", () => {
    render(<SimulatedBadge isSimulated />);
    expect(screen.getByTestId("badge-simulated")).toBeTruthy();
  });

  it("renders nothing when the API asserted nothing", () => {
    // The property that makes the badge evidence: no data, no claim.
    const { container } = render(<SimulatedBadge />);
    expect(container.innerHTML).toBe("");
  });

  it("does not claim SIMULATED when the API reports something else", () => {
    render(<SimulatedBadge status="IMPLEMENTED" />);
    expect(screen.queryByTestId("badge-simulated")).toBeNull();
    expect(screen.getByTestId("badge-implemented").textContent).toContain("IMPLEMENTED");
  });

  it("distinguishes a replayed model response from a simulated adapter", () => {
    render(<SimulatedBadge status="SIMULATED" isReplay />);
    expect(screen.getByTestId("badge-simulated")).toBeTruthy();
    expect(screen.getByTestId("badge-replay").textContent).toContain("REPLAY");
  });
});

describe("SimulatedBanner", () => {
  it("states the environment and that no live call has been made", () => {
    render(<SimulatedBanner />);
    expect(screen.getByRole("status").textContent).toContain("SIMULATED ENVIRONMENT");
    expect(screen.getByRole("status").textContent).toContain("never made a live API call");
  });

  it("is separate from the row badge, so one cannot substitute for the other", () => {
    // Rendering the banner alone must not produce any row-level badge.
    const { container } = render(<SimulatedBanner />);
    expect(container.querySelector("[data-testid^='badge-']")).toBeNull();
  });
});
