/**
 * Formatting rules that carry meaning rather than taste.
 *
 * The backend serialises money as strings so a `Decimal` survives JSON. If this layer
 * parsed them into JavaScript numbers, the loss the backend avoided would reappear in
 * the last inch of the pipeline -- so these tests pin the behaviour that prevents it.
 */
import { describe, expect, it } from "vitest";
import { NOT_RECORDED, formatCost, formatMoney, formatTraceId, shortId } from "@/lib/format";

describe("formatCost", () => {
  it("keeps six decimals so sub-cent spend stays visible", () => {
    // The entire reason cost_entries.amount_usd is NUMERIC(12, 6).
    expect(formatCost("0.000150")).toBe("$0.000150");
  });

  it("renders zero as $0.000000 and never as $0.00", () => {
    expect(formatCost("0.000000")).toBe("$0.000000");
    expect(formatCost("0.000000")).not.toBe("$0.00");
    expect(formatCost("0.000000")).not.toBe("$0");
  });

  it("pads a short fraction rather than trimming it", () => {
    expect(formatCost("1.5")).toBe("$1.500000");
    expect(formatCost("2")).toBe("$2.000000");
  });

  it("never loses precision through a float round-trip", () => {
    // 0.1 + 0.2 !== 0.3 in IEEE754. A string passes through untouched.
    expect(formatCost("0.100000")).toBe("$0.100000");
    expect(formatCost("12345678.123456")).toBe("$12,345,678.123456");
  });

  it("shows an absent cost as absent", () => {
    expect(formatCost(null)).toBe("—");
    expect(formatCost(undefined)).toBe("—");
  });
});

describe("formatMoney", () => {
  it("formats pipeline figures with grouping and the currency", () => {
    expect(formatMoney("108000.00")).toBe("$108,000.00 USD");
    expect(formatMoney("32130.00")).toBe("$32,130.00 USD");
  });

  it("preserves the backend's decimals exactly", () => {
    expect(formatMoney("180000.00")).toContain("180,000.00");
  });

  it("handles a missing value", () => {
    expect(formatMoney(null)).toBe("—");
  });
});

describe("tracing identifiers", () => {
  it("renders an absent id as explicit text, never a fabricated value", () => {
    expect(formatTraceId(null)).toBe(NOT_RECORDED);
    expect(formatTraceId(undefined)).toBe(NOT_RECORDED);
    expect(shortId(null)).toBe(NOT_RECORDED);
  });

  it("truncates a long id without inventing one", () => {
    const trace = "a".repeat(32);
    expect(shortId(trace)).toBe(`${"a".repeat(12)}…`);
    expect(shortId(trace)).not.toHaveLength(32);
  });

  it("passes a short id through unchanged", () => {
    expect(shortId("abc123")).toBe("abc123");
  });
});
