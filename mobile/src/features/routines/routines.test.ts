import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Routines: the API contract and the two display helpers.
 *
 * The grouping matters more than it looks. A routine's folder is user-typed text, so the
 * grouping has to survive a null, a duplicate, and an ordering that would otherwise
 * depend on whatever order the server happened to return.
 */

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));

const { api } = await import("@/lib/api/client");
const { routinesApi, prescription, byFolder } = await import("./api");

function routine(overrides: Partial<import("./api").Routine> = {}) {
  return {
    id: "routine-1",
    name: "Push A",
    folder: null,
    notes: null,
    isTemplate: false,
    estimatedMinutes: null,
    version: 1,
    lastPerformedAt: null,
    totalSets: 9,
    exercises: [],
    ...overrides,
  };
}

function set(overrides: Partial<import("./api").RoutineSet> = {}) {
  return {
    id: "set-1",
    setNumber: 1,
    setType: "normal",
    targetRepsMin: 8,
    targetRepsMax: 12,
    targetWeightKg: null,
    targetDurationSeconds: null,
    targetDistanceM: null,
    targetRpe: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("the API contract", () => {
  it("sends the read version on an edit so a conflict is reported", async () => {
    // Optimistic locking. Omitting it forces the write and silently overwrites whatever
    // another device changed in between.
    vi.mocked(api.patch).mockResolvedValue(routine());
    await routinesApi.update("routine-1", { name: "Push B", version: 3 });

    const [path, body] = vi.mocked(api.patch).mock.calls[0] as [string, { version: number }];
    expect(path).toBe("/v1/workouts/routines/routine-1");
    expect(body.version).toBe(3);
  });

  it("replaces the whole exercise list rather than patching it", async () => {
    vi.mocked(api.put).mockResolvedValue(routine());
    await routinesApi.replaceExercises("routine-1", [{ exerciseId: "bench", sets: [{}] }]);

    const [path, body] = vi.mocked(api.put).mock.calls[0] as [
      string,
      { exercises: unknown[] },
    ];
    expect(path).toBe("/v1/workouts/routines/routine-1/exercises");
    expect(body.exercises).toHaveLength(1);
  });

  it("duplicates without a name when none is given", async () => {
    vi.mocked(api.post).mockResolvedValue(routine());
    await routinesApi.duplicate("routine-1");

    const [, body] = vi.mocked(api.post).mock.calls[0] as [string, Record<string, unknown>];
    expect(body).toEqual({});
  });

  it("adopts a template by its own id", async () => {
    vi.mocked(api.post).mockResolvedValue(routine());
    await routinesApi.adopt("template-9");

    const [path] = vi.mocked(api.post).mock.calls[0] as [string];
    expect(path).toBe("/v1/workouts/routines/templates/template-9/adopt");
  });
});

describe("the prescription line", () => {
  it("reads as sets by rep range", () => {
    expect(prescription([set(), set(), set()])).toBe("3 × 8–12");
  });

  it("collapses a range that is one number", () => {
    expect(prescription([set({ targetRepsMin: 5, targetRepsMax: 5 })])).toBe("1 × 5");
  });

  it("uses whichever bound is prescribed", () => {
    expect(prescription([set({ targetRepsMax: null })])).toBe("1 × 8");
    expect(prescription([set({ targetRepsMin: null })])).toBe("1 × 12");
  });

  it("says how many sets when no reps are prescribed", () => {
    // A real case: timed or distance work. "3 × null" would be worse than saying less.
    expect(
      prescription([
        set({ targetRepsMin: null, targetRepsMax: null }),
        set({ targetRepsMin: null, targetRepsMax: null }),
      ]),
    ).toBe("2 sets");
  });

  it("is empty for an exercise with no sets", () => {
    expect(prescription([])).toBe("");
  });
});

describe("grouping by folder", () => {
  it("puts each folder together", () => {
    const grouped = byFolder([
      routine({ id: "a", folder: "Push" }),
      routine({ id: "b", folder: "Pull" }),
      routine({ id: "c", folder: "Push" }),
    ]);

    expect(grouped.map(([folder]) => folder)).toEqual(["Pull", "Push"]);
    expect(grouped[1]?.[1].map((r) => r.id)).toEqual(["a", "c"]);
  });

  it("puts unfoldered routines last", () => {
    // A folder is a deliberate act of organisation and earns the top of the list.
    const grouped = byFolder([routine({ id: "a" }), routine({ id: "b", folder: "Push" })]);

    expect(grouped.map(([folder]) => folder)).toEqual(["Push", null]);
  });

  it("sorts folders by name rather than by arrival", () => {
    const grouped = byFolder([
      routine({ id: "a", folder: "Zebra" }),
      routine({ id: "b", folder: "Alpha" }),
    ]);

    expect(grouped.map(([folder]) => folder)).toEqual(["Alpha", "Zebra"]);
  });

  it("is empty for no routines", () => {
    expect(byFolder([])).toEqual([]);
  });

  it("keeps every routine", () => {
    const grouped = byFolder([
      routine({ id: "a", folder: "Push" }),
      routine({ id: "b" }),
      routine({ id: "c", folder: "Push" }),
    ]);

    expect(grouped.flatMap(([, items]) => items)).toHaveLength(3);
  });
});
