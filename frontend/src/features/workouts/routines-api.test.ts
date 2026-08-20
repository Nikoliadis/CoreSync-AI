import { describe, expect, it } from "vitest";

import { groupByFolder, type Routine } from "@/features/workouts/routines-api";

function routine(name: string, folder: string | null): Routine {
  return {
    id: name,
    name,
    folder,
    notes: null,
    isTemplate: false,
    estimatedMinutes: null,
    version: 1,
    lastPerformedAt: null,
    exercises: [],
  };
}

describe("groupByFolder", () => {
  it("groups routines under their folder", () => {
    const grouped = groupByFolder([
      routine("Push", "PPL"),
      routine("Pull", "PPL"),
      routine("Squat day", "Strength"),
    ]);

    expect(grouped.map(([folder]) => folder)).toEqual(["PPL", "Strength"]);
    expect(grouped[0][1].map((r) => r.name)).toEqual(["Push", "Pull"]);
  });

  it("puts unfiled routines last", () => {
    // A deliberate rule, not the API's incidental ordering: folders are the thing the
    // user organised, so what they did not file belongs at the bottom.
    const grouped = groupByFolder([
      routine("Loose", null),
      routine("Push", "PPL"),
      routine("Also loose", null),
    ]);

    expect(grouped.at(-1)?.[0]).toBe("");
    expect(grouped.at(-1)?.[1]).toHaveLength(2);
  });

  it("sorts folders alphabetically", () => {
    const grouped = groupByFolder([
      routine("c", "Zeta"),
      routine("a", "Alpha"),
      routine("b", "Mid"),
    ]);

    expect(grouped.map(([folder]) => folder)).toEqual(["Alpha", "Mid", "Zeta"]);
  });

  it("handles an empty list", () => {
    expect(groupByFolder([])).toEqual([]);
  });

  it("keeps routines in their given order within a folder", () => {
    const grouped = groupByFolder([routine("second", "F"), routine("first", "F")]);
    expect(grouped[0][1].map((r) => r.name)).toEqual(["second", "first"]);
  });
});
