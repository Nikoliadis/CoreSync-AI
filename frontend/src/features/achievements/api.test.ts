import { describe, expect, it } from "vitest";

import { progressLabel, type Achievement } from "@/features/achievements/api";

function achievement(currentValue: string, threshold: string): Achievement {
  return {
    code: "x",
    name: "x",
    description: "x",
    category: "volume",
    tier: "bronze",
    threshold,
    earned: false,
    earnedAt: null,
    progress: "0",
    currentValue,
  };
}

describe("progressLabel", () => {
  it("reads as a count towards the target", () => {
    expect(progressLabel(achievement("7", "10"))).toBe("7 of 10");
  });

  it("abbreviates thousands", () => {
    expect(progressLabel(achievement("45000", "100000"))).toBe("45k of 100k");
  });

  it("abbreviates millions", () => {
    // "1,000,000 kg" is a wall of digits that hides the thing it is communicating.
    expect(progressLabel(achievement("500000", "1000000"))).toBe("500k of 1M");
  });

  it("keeps one decimal on a partial million", () => {
    expect(progressLabel(achievement("1500000", "5000000"))).toBe("1.5M of 5M");
  });

  it("never shows more than the target", () => {
    // Overshooting is normal once earned; "12 of 10" reads like a bug.
    expect(progressLabel(achievement("12", "10"))).toBe("10 of 10");
  });

  it("returns nothing for unparseable values", () => {
    expect(progressLabel(achievement("abc", "10"))).toBe("");
  });
});
