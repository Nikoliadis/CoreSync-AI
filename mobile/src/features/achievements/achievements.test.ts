import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Achievements: the ranking, and what an unearned badge says.
 *
 * The ranking is the feature. A grid sorted by definition order shows whichever badge
 * happens to be first in the seed file; sorted by progress it shows the one you are two
 * workouts away from. Those are different products.
 */

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  ApiError: class extends Error {},
}));

const { progressPct, progressLabel, ranked, byCategory, tierColour, CATEGORIES, CATEGORY_LABELS } =
  await import("./api");

function badge(overrides: Partial<import("./api").Achievement> = {}) {
  return {
    code: "first-workout",
    name: "First workout",
    description: "Log your first session.",
    category: "milestone",
    tier: "bronze",
    threshold: "1",
    earned: false,
    earnedAt: null,
    progress: "0",
    currentValue: "0",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("progress on an unearned badge", () => {
  it("is a percentage of the way there", () => {
    expect(progressPct(badge({ progress: "0.7" }))).toBeCloseTo(70);
  });

  it("clamps a value the server should already have clamped", () => {
    // Trusting a remote number and feeding it to a width style renders the bar outside
    // its own container.
    expect(progressPct(badge({ progress: "1.4" }))).toBe(100);
    expect(progressPct(badge({ progress: "-0.2" }))).toBe(0);
  });

  it("is zero rather than NaN on a malformed value", () => {
    expect(progressPct(badge({ progress: "" }))).toBe(0);
  });

  it("reads as a count, not a lab result", () => {
    expect(progressLabel(badge({ currentValue: "7", threshold: "10" }))).toBe("7 of 10");
  });

  it("groups large thresholds so volume stays readable", () => {
    const label = progressLabel(badge({ currentValue: "45000", threshold: "100000" }));
    expect(label).toBe(`${(45000).toLocaleString()} of ${(100000).toLocaleString()}`);
  });

  it("never claims more progress than the threshold", () => {
    // The server can report a current value past the threshold in the window between
    // earning and evaluation. "11 of 10" looks like a bug.
    expect(progressLabel(badge({ currentValue: "11", threshold: "10" }))).toBe("10 of 10");
  });

  it("is empty rather than NaN when the numbers are unusable", () => {
    expect(progressLabel(badge({ currentValue: "x", threshold: "y" }))).toBe("");
  });
});

describe("ranking", () => {
  it("puts earned badges before unearned ones", () => {
    const order = ranked([
      badge({ code: "a", earned: false, progress: "0.9" }),
      badge({ code: "b", earned: true, earnedAt: "2026-08-01T00:00:00Z" }),
    ]).map((item) => item.code);

    expect(order).toEqual(["b", "a"]);
  });

  it("shows the most recently earned first", () => {
    const order = ranked([
      badge({ code: "old", earned: true, earnedAt: "2026-01-01T00:00:00Z" }),
      badge({ code: "new", earned: true, earnedAt: "2026-08-01T00:00:00Z" }),
    ]).map((item) => item.code);

    expect(order).toEqual(["new", "old"]);
  });

  it("shows the closest unearned badge first", () => {
    // The whole point: the one two workouts away, not the one requiring a hundred.
    const order = ranked([
      badge({ code: "far", progress: "0.1" }),
      badge({ code: "near", progress: "0.8" }),
    ]).map((item) => item.code);

    expect(order).toEqual(["near", "far"]);
  });

  it("does not mutate the array it was given", () => {
    const input = [badge({ code: "a", progress: "0.1" }), badge({ code: "b", progress: "0.9" })];
    ranked(input);
    expect(input.map((item) => item.code)).toEqual(["a", "b"]);
  });

  it("handles an empty list", () => {
    expect(ranked([])).toEqual([]);
  });
});

describe("grouping by category", () => {
  it("returns only categories that have badges", () => {
    const groups = byCategory([badge({ category: "strength" })]);
    expect(groups.map(([category]) => category)).toEqual(["strength"]);
  });

  it("keeps the ranking inside each group", () => {
    const groups = byCategory([
      badge({ code: "far", category: "volume", progress: "0.1" }),
      badge({ code: "near", category: "volume", progress: "0.9" }),
    ]);
    expect(groups[0]?.[1].map((item) => item.code)).toEqual(["near", "far"]);
  });

  it("drops a badge whose category the client does not know", () => {
    // Better than rendering a section header reading "undefined".
    expect(byCategory([badge({ category: "something-new" })])).toEqual([]);
  });

  it("every known category has a label", () => {
    for (const category of CATEGORIES) {
      expect(CATEGORY_LABELS[category]).toBeTruthy();
    }
  });
});

describe("tiers", () => {
  it("has a colour for each tier", () => {
    expect(tierColour("bronze")).not.toBe(tierColour("gold"));
    expect(tierColour("silver")).toBeTruthy();
  });

  it("falls back rather than rendering undefined for an unknown tier", () => {
    expect(tierColour("platinum")).toBe(tierColour("bronze"));
  });
});
