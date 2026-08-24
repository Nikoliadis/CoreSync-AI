import { describe, expect, it } from "vitest";

import { friendlyDate, kcal, localToday, macroSlots, portion, shiftDate } from "./format";

describe("shiftDate", () => {
  it("steps back a day", () => {
    expect(shiftDate("2026-08-21", -1)).toBe("2026-08-20");
  });

  it("crosses a month boundary", () => {
    expect(shiftDate("2026-09-01", -1)).toBe("2026-08-31");
  });

  it("crosses a year boundary", () => {
    expect(shiftDate("2027-01-01", -1)).toBe("2026-12-31");
  });

  it("handles a leap day", () => {
    expect(shiftDate("2028-02-28", 1)).toBe("2028-02-29");
  });

  it("survives a spring-forward date", () => {
    // The EU shifts on the last Sunday of March. Building the date at local midnight and
    // re-normalising through the offset is what keeps this from landing on the 28th.
    expect(shiftDate("2026-03-28", 1)).toBe("2026-03-29");
    expect(shiftDate("2026-03-29", 1)).toBe("2026-03-30");
  });

  it("survives an autumn fall-back date", () => {
    expect(shiftDate("2026-10-24", 1)).toBe("2026-10-25");
    expect(shiftDate("2026-10-25", 1)).toBe("2026-10-26");
  });

  it("round-trips", () => {
    expect(shiftDate(shiftDate("2026-08-21", -7), 7)).toBe("2026-08-21");
  });
});

describe("localToday", () => {
  it("is an ISO date, not a timestamp", () => {
    expect(localToday()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("agrees with the browser's own idea of the date", () => {
    // The bug this guards against is using `toISOString()` directly: at 01:00 in Athens
    // that returns the previous UTC day, and the diary opens on yesterday.
    const now = new Date();
    const expected = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, "0"),
      String(now.getDate()).padStart(2, "0"),
    ].join("-");
    expect(localToday()).toBe(expected);
  });
});

describe("friendlyDate", () => {
  it("names today", () => {
    expect(friendlyDate(localToday())).toBe("Today");
  });

  it("names yesterday", () => {
    expect(friendlyDate(shiftDate(localToday(), -1))).toBe("Yesterday");
  });

  it("formats anything further back", () => {
    const older = shiftDate(localToday(), -9);
    expect(friendlyDate(older)).not.toBe("Today");
    expect(friendlyDate(older)).not.toBe("Yesterday");
  });
});

describe("kcal", () => {
  it("rounds the wire decimal", () => {
    expect(kcal("330.40")).toBe(330);
    expect(kcal("330.60")).toBe(331);
  });

  it("treats a missing value as zero rather than NaN", () => {
    expect(kcal(null)).toBe(0);
    expect(kcal(undefined)).toBe(0);
  });
});

describe("portion", () => {
  it("drops a meaningless decimal", () => {
    expect(portion("116.000")).toBe("116");
  });

  it("keeps one that says something", () => {
    expect(portion("0.500")).toBe("0.5");
  });
});

describe("macroSlots", () => {
  it("always returns the three macros, even with no data", () => {
    expect(macroSlots(null).map((s) => s.key)).toEqual(["protein", "carbs", "fat"]);
    expect(macroSlots(null).every((s) => s.grams === 0)).toBe(true);
  });

  it("reads the wire fields", () => {
    const slots = macroSlots({
      calories: "2000",
      proteinG: "150.4",
      carbsG: "200.6",
      fatG: "70",
      alcoholG: "0",
    });
    expect(slots.map((s) => s.grams)).toEqual([150, 201, 70]);
  });
});
