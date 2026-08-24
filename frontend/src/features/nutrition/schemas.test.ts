import { describe, expect, it } from "vitest";

import { createFoodSchema, impliedCalories } from "./schemas";

const base = {
  name: "Test food",
  caloriesPer100g: 0,
  proteinPer100g: 0,
  carbsPer100g: 0,
  fatPer100g: 0,
  alcoholPer100g: 0,
  isLiquid: false,
};

function parse(overrides: Partial<typeof base> & Record<string, unknown> = {}) {
  return createFoodSchema.safeParse({ ...base, ...overrides });
}

function errorsOn(result: ReturnType<typeof parse>, path: string): string[] {
  if (result.success) return [];
  return result.error.issues.filter((i) => i.path[0] === path).map((i) => i.message);
}

describe("impliedCalories", () => {
  it("applies the Atwater factors", () => {
    expect(
      impliedCalories({
        proteinPer100g: 10,
        carbsPer100g: 20,
        fatPer100g: 5,
        alcoholPer100g: 0,
      }),
    ).toBe(10 * 4 + 20 * 4 + 5 * 9);
  });

  it("counts ethanol at 7 kcal per gram", () => {
    expect(
      impliedCalories({
        proteinPer100g: 0,
        carbsPer100g: 0,
        fatPer100g: 0,
        alcoholPer100g: 10,
      }),
    ).toBe(70);
  });
});

describe("the energy check", () => {
  it("accepts macros that reconcile", () => {
    // 31 g protein and 3.6 g fat is 156 kcal against a stated 165 — well inside band.
    expect(parse({ caloriesPer100g: 165, proteinPer100g: 31, fatPer100g: 3.6 }).success).toBe(
      true,
    );
  });

  it("rejects a misplaced decimal point and names the right number", () => {
    const result = parse({
      caloriesPer100g: 40,
      proteinPer100g: 80,
      carbsPer100g: 8,
      fatPer100g: 6,
    });
    expect(result.success).toBe(false);
    expect(errorsOn(result, "caloriesPer100g")[0]).toContain("406");
  });

  it("lets a low-calorie food through on the absolute floor", () => {
    // Vegetables never reconcile proportionally — the fibre is not a tracked macro —
    // so the 50 kcal floor is what keeps a lettuce from being rejected as a typo.
    expect(parse({ caloriesPer100g: 18, proteinPer100g: 0.9, carbsPer100g: 3.9 }).success).toBe(
      true,
    );
  });

  it("accepts a spirit, whose calories are almost all ethanol", () => {
    // The case that migration 0009 exists for: without alcohol as a term, this reads
    // as a typo and gets refused.
    expect(parse({ caloriesPer100g: 225, alcoholPer100g: 32 }).success).toBe(true);
  });

  it("rejects a spirit if the alcohol is left out", () => {
    expect(parse({ caloriesPer100g: 225 }).success).toBe(false);
  });

  it("skips the check for a zero-calorie food", () => {
    // Water, black coffee, a diet drink. Nothing to reconcile against.
    expect(parse({ caloriesPer100g: 0 }).success).toBe(true);
  });

  it("widens the band proportionally for calorie-dense foods", () => {
    // Olive oil: 884 stated, 900 implied. Sixteen kcal apart, and comfortably inside
    // a 25% band that a fixed 50 kcal floor would also have allowed.
    expect(parse({ caloriesPer100g: 884, fatPer100g: 100 }).success).toBe(true);
  });
});

describe("field validation", () => {
  it("requires a name", () => {
    expect(errorsOn(parse({ name: "  " }), "name")).toHaveLength(1);
  });

  it("rejects negative macros", () => {
    expect(errorsOn(parse({ proteinPer100g: -1 }), "proteinPer100g")).toHaveLength(1);
  });

  it("caps a macro at 100 g per 100 g", () => {
    expect(errorsOn(parse({ proteinPer100g: 310 }), "proteinPer100g")).toHaveLength(1);
  });
});

describe("servings", () => {
  it("accepts a complete serving", () => {
    const result = parse({ servingLabel: "1 slice", servingGrams: 35 });
    expect(result.success).toBe(true);
  });

  it("accepts no serving at all", () => {
    expect(parse().success).toBe(true);
  });

  it("rejects a label with no weight", () => {
    expect(errorsOn(parse({ servingLabel: "1 slice" }), "servingGrams")).toHaveLength(1);
  });

  it("rejects a weight with no label", () => {
    expect(errorsOn(parse({ servingGrams: 35 }), "servingLabel")).toHaveLength(1);
  });
});
