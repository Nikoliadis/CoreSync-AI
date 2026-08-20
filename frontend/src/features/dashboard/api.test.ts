import { describe, expect, it } from "vitest";

import { percentChange } from "@/features/dashboard/api";

describe("percentChange", () => {
  it("reports a rise", () => {
    expect(percentChange(120, 100)).toBe(20);
  });

  it("reports a fall", () => {
    expect(percentChange(80, 100)).toBe(-20);
  });

  it("returns null with no baseline", () => {
    // A first week has nothing to compare against. Showing +0% there would state
    // something false rather than admit there is no comparison.
    expect(percentChange(500, 0)).toBeNull();
  });

  it("returns null for non-finite input", () => {
    expect(percentChange(Number.NaN, 100)).toBeNull();
    expect(percentChange(100, Number.NaN)).toBeNull();
  });

  it("reports zero when genuinely unchanged", () => {
    expect(percentChange(100, 100)).toBe(0);
  });
});
