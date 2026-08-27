import { describe, expect, it, vi } from "vitest";

/**
 * Settings: unit conversion and age.
 *
 * The height conversion is the one with a classic bug in it. Rounding total inches before
 * splitting into feet gives 5'12" instead of 6'0", which is not wrong by much but is
 * obviously broken to anybody who reads it.
 *
 * Age matters because Mifflin-St Jeor uses it. Off by a year is off by roughly ten
 * calories a day, every day, silently.
 */

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));

const { toFeetInches, heightLabel, ageFrom, ACTIVITY_LEVELS, ACTIVITY_LABELS, EXPERIENCE_LEVELS, EXPERIENCE_LABELS } =
  await import("./api");

describe("height in feet and inches", () => {
  it("converts a common height", () => {
    expect(toFeetInches(178)).toEqual({ feet: 5, inches: 10 });
  });

  it("never produces twelve inches", () => {
    // 182.5cm is 71.85", which rounds to 72" — that must read 6'0", not 5'12".
    const result = toFeetInches(182.5);
    expect(result.inches).toBeLessThan(12);
    expect(result).toEqual({ feet: 6, inches: 0 });
  });

  it("carries into the next foot correctly", () => {
    expect(toFeetInches(183)).toEqual({ feet: 6, inches: 0 });
  });

  it("handles an exact conversion", () => {
    expect(toFeetInches(152.4)).toEqual({ feet: 5, inches: 0 });
  });
});

describe("the height label", () => {
  it("uses centimetres for metric", () => {
    expect(heightLabel("178.00", "metric")).toBe("178 cm");
  });

  it("uses feet and inches for imperial", () => {
    expect(heightLabel("178.00", "imperial")).toBe(`5'10"`);
  });

  it("is a dash when height is unknown", () => {
    expect(heightLabel(null, "metric")).toBe("—");
    expect(heightLabel("0", "metric")).toBe("—");
    expect(heightLabel("nonsense", "metric")).toBe("—");
  });
});

describe("age from a date of birth", () => {
  const today = new Date(2026, 7, 27);

  it("counts completed years", () => {
    expect(ageFrom("1990-08-27", today)).toBe(36);
  });

  it("does not count a birthday that has not happened yet this year", () => {
    // Off by one here is roughly ten calories a day, every day, silently.
    expect(ageFrom("1990-08-28", today)).toBe(35);
  });

  it("counts a birthday earlier this month", () => {
    expect(ageFrom("1990-08-01", today)).toBe(36);
  });

  it("handles a birthday in a later month", () => {
    expect(ageFrom("1990-12-01", today)).toBe(35);
  });

  it("is absent when unknown", () => {
    expect(ageFrom(null, today)).toBeNull();
  });

  it("is absent rather than negative for a future date", () => {
    expect(ageFrom("2030-01-01", today)).toBeNull();
  });

  it("is absent for a malformed date", () => {
    expect(ageFrom("not-a-date", today)).toBeNull();
  });

  it("rejects an implausible age rather than displaying it", () => {
    expect(ageFrom("1800-01-01", today)).toBeNull();
  });
});

describe("the vocabularies are presentable", () => {
  it("every activity level has a label", () => {
    for (const level of ACTIVITY_LEVELS) {
      expect(ACTIVITY_LABELS[level]).toBeTruthy();
    }
  });

  it("every experience level has a label", () => {
    for (const level of EXPERIENCE_LEVELS) {
      expect(EXPERIENCE_LABELS[level]).toBeTruthy();
    }
  });
});
