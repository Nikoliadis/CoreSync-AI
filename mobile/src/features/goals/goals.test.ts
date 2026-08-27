import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Goals: the sign convention, and the advice about rates.
 *
 * The sign convention is where this can go quietly wrong. The field asks for a magnitude
 * ("0.5 kg a week") because "-0.5 to lose" is a double negative nobody types correctly,
 * so the screen has to apply the sign itself. Send a positive rate with a fat-loss goal
 * and the server computes a surplus — the user asked to lose weight and would be told to
 * eat more.
 */

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
  ApiError: class extends Error {},
}));

const { api } = await import("@/lib/api/client");
const {
  rateWarning,
  goalSummary,
  macroSplit,
  signedWeeklyRate,
  GOAL_TYPES,
  GOAL_LABELS,
  GOAL_BLURBS,
} = await import("./api");

function goal(overrides: Partial<import("./api").Goal> = {}) {
  return {
    id: "goal-1",
    goalType: "lose_fat" as const,
    targetWeightKg: "78.00",
    weeklyRateKg: "-0.50",
    targetDate: null,
    startedOn: "2026-08-01",
    endedOn: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("advice about the rate", () => {
  it("warns when fat loss is faster than about 1% of bodyweight a week", () => {
    // Past that, the losses stop being mostly fat. Worth saying before somebody commits
    // to a plan, not after eight weeks of it.
    expect(rateWarning("lose_fat", 1.2, 90)).toContain("muscle");
  });

  it("scales the ceiling to the person, not to a fixed number", () => {
    // 0.9 kg/week is aggressive at 60 kg and unremarkable at 120 kg.
    expect(rateWarning("lose_fat", 0.9, 60)).not.toBeNull();
    expect(rateWarning("lose_fat", 0.9, 120)).toBeNull();
  });

  it("falls back to a sane ceiling when bodyweight is unknown", () => {
    expect(rateWarning("lose_fat", 1.5, null)).not.toBeNull();
    expect(rateWarning("lose_fat", 0.4, null)).toBeNull();
  });

  it("warns about gaining faster than half a kilo a week", () => {
    expect(rateWarning("gain_muscle", 0.8, 80)).toContain("fat");
  });

  it("does not warn about a reasonable rate", () => {
    expect(rateWarning("lose_fat", 0.5, 90)).toBeNull();
    expect(rateWarning("gain_muscle", 0.25, 80)).toBeNull();
  });

  it("says nothing when no rate was given", () => {
    expect(rateWarning("lose_fat", null, 90)).toBeNull();
    expect(rateWarning("lose_fat", 0, 90)).toBeNull();
  });

  it("says nothing for goals that are not about the scale", () => {
    expect(rateWarning("maintain", 2, 80)).toBeNull();
    expect(rateWarning("performance", 2, 80)).toBeNull();
    expect(rateWarning("recomp", 2, 80)).toBeNull();
  });

  it("reads a magnitude regardless of sign", () => {
    // The field collects a magnitude; the screen applies the sign. The warning must not
    // depend on which one it happens to receive.
    expect(rateWarning("lose_fat", -1.2, 90)).toEqual(rateWarning("lose_fat", 1.2, 90));
  });
});

describe("summarising a goal", () => {
  it("names the destination and the date when both are set", () => {
    expect(goalSummary(goal({ targetDate: "2026-12-01" }))).toBe("78.0 kg by 2026-12-01");
  });

  it("names just the weight when there is no date", () => {
    expect(goalSummary(goal())).toBe("78.0 kg");
  });

  it("says maintenance is holding steady, not a weight", () => {
    expect(goalSummary(goal({ goalType: "maintain" }))).toBe("Holding steady");
  });

  it("falls back to the goal name when no weight is set", () => {
    expect(goalSummary(goal({ goalType: "performance", targetWeightKg: null }))).toBe(
      "Performance",
    );
  });

  it("is absent when no goal has been set", () => {
    expect(goalSummary(null)).toBeNull();
  });
});

describe("every goal type is presentable", () => {
  it("has a label and a blurb, so none renders as a raw enum", () => {
    for (const type of GOAL_TYPES) {
      expect(GOAL_LABELS[type]).toBeTruthy();
      expect(GOAL_BLURBS[type]).toBeTruthy();
    }
  });
});

describe("daily targets", () => {
  it("rounds to whole numbers, because grams to a decimal is false precision", () => {
    const split = macroSplit({
      id: "t",
      effectiveFrom: "2026-08-01",
      effectiveTo: null,
      calories: "2150.40",
      proteinG: "165.60",
      carbsG: "210.20",
      fatG: "70.80",
      fiberG: null,
      waterMl: "3000",
      source: "calculated",
      rationale: null,
    });

    expect(split).toEqual({ calories: 2150, protein: 166, carbs: 210, fat: 71 });
  });

  it("is absent when no targets have been set", () => {
    expect(macroSplit(null)).toBeNull();
  });
});

describe("the API contract", () => {
  it("recalculating targets is a separate call from setting the goal", async () => {
    // They are genuinely two things. Doing only the first leaves somebody with a stated
    // goal and yesterday's calories.
    const { goalsApi } = await import("./api");
    vi.mocked(api.post).mockResolvedValue({});

    await goalsApi.setGoal({ goalType: "lose_fat", weeklyRateKg: -0.5 });
    await goalsApi.recalculateTargets();

    const paths = vi.mocked(api.post).mock.calls.map((call) => call[0]);
    expect(paths).toEqual(["/v1/users/me/goals", "/v1/users/me/targets/recalculate"]);
  });
});

describe("the sign convention", () => {
  it("makes a fat-loss rate negative", () => {
    // The field collects a magnitude. Sending it unsigned would make the server compute
    // a surplus, so somebody who asked to lose weight would be told to eat more.
    expect(signedWeeklyRate("lose_fat", 0.5)).toBe(-0.5);
  });

  it("leaves a gaining rate positive", () => {
    expect(signedWeeklyRate("gain_muscle", 0.25)).toBe(0.25);
  });

  it("ignores whichever sign the field happened to contain", () => {
    // Someone typing "-0.5" into a field labelled "kg per week" means the same thing.
    expect(signedWeeklyRate("lose_fat", -0.5)).toBe(-0.5);
    expect(signedWeeklyRate("gain_muscle", -0.25)).toBe(0.25);
  });

  it("is absent rather than zero when nothing was entered", () => {
    expect(signedWeeklyRate("lose_fat", null)).toBeNull();
    expect(signedWeeklyRate("lose_fat", 0)).toBeNull();
    expect(signedWeeklyRate("lose_fat", Number.NaN)).toBeNull();
  });

  it("does not invert the rate for goals that are not fat loss", () => {
    for (const type of ["maintain", "recomp", "performance"] as const) {
      expect(signedWeeklyRate(type, 0.4)).toBe(0.4);
    }
  });
});
