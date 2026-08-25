import { describe, expect, it, vi } from "vitest";

/**
 * Previous performance and the PR badge.
 *
 * Both are claims made to the user's face — "this is what you did last time", "this beat
 * your record" — and both are wrong in a way that is hard to notice: an empty PREV column
 * looks like a first session, and a missing trophy looks like a set that fell short.
 *
 * The record type and the 1RM formula are therefore pinned against the server's, because
 * the failure mode of drifting from it is silence rather than an error.
 */

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn() },
  ApiError: class extends Error {},
}));

const { previousSet, formatPrevious, estimatedOneRepMax, beatsRecord, recordSetId } =
  await import("./history-api");

function set(overrides: Partial<import("./history-api").HistorySet> = {}) {
  return {
    id: "set-1",
    setNumber: 1,
    setType: "normal",
    reps: 8,
    weightKg: "80.00",
    rpe: null,
    isCompleted: true,
    estimatedOneRepMax: "101.33",
    ...overrides,
  };
}

function history(sets: ReturnType<typeof set>[]) {
  return {
    exerciseId: "bench",
    exerciseName: "Bench Press",
    totalSessions: 1,
    totalSets: sets.length,
    totalVolumeKg: "1920.00",
    bestEstimatedOneRepMax: "101.33",
    lastPerformedOn: "2026-08-18",
    sessions: [
      {
        sessionId: "session-0",
        sessionName: "Push",
        localDate: "2026-08-18",
        totalVolumeKg: "1920.00",
        bestSetId: "set-1",
        sets,
      },
    ],
  };
}

function record(overrides: Partial<import("./history-api").PersonalRecord> = {}) {
  return {
    id: "pr-1",
    exerciseId: "bench",
    exerciseName: "Bench Press",
    recordType: "est_1rm",
    value: "101.33",
    repsAtValue: 8,
    achievedOn: "2026-08-18",
    isCurrent: true,
    previousValue: null,
    improvement: null,
    ...overrides,
  };
}

describe("what you did last time", () => {
  it("matches by set number, not by best set", () => {
    const found = previousSet(
      history([set({ setNumber: 1, reps: 8 }), set({ id: "set-2", setNumber: 2, reps: 6 })]),
      2,
    );
    expect(found?.reps).toBe(6);
  });

  it("falls back to the last set when the previous session was shorter", () => {
    // More useful than showing nothing: set 5 of today against set 3 of last time still
    // tells you what the bar felt like.
    const found = previousSet(history([set({ setNumber: 1 }), set({ id: "s2", setNumber: 2 })]), 5);
    expect(found?.setNumber).toBe(2);
  });

  it("is empty for an exercise never performed", () => {
    expect(previousSet(undefined, 1)).toBeNull();
  });

  it("is empty when the last session logged nothing", () => {
    expect(previousSet(history([]), 1)).toBeNull();
  });

  it("formats weight and reps the way the row reads", () => {
    expect(formatPrevious(set({ weightKg: "80.00", reps: 8 }))).toBe("80 × 8");
  });

  it("keeps a half-kilo but drops a meaningless decimal", () => {
    expect(formatPrevious(set({ weightKg: "82.50" }))).toBe("82.5 × 8");
  });

  it("says reps alone for bodyweight work", () => {
    expect(formatPrevious(set({ weightKg: null, reps: 12 }))).toBe("12 reps");
  });

  it("shows nothing for a row that carried neither", () => {
    expect(formatPrevious(set({ weightKg: null, reps: null }))).toBeNull();
    expect(formatPrevious(null)).toBeNull();
  });
});

describe("the 1RM estimate", () => {
  it("matches the server on a worked example", () => {
    // Epley: 80 × (1 + 8/30) = 101.33, which is what `estimated_one_rep_max` stores.
    expect(estimatedOneRepMax(80, 8)).toBeCloseTo(101.33, 2);
  });

  it("returns the weight itself for a single", () => {
    expect(estimatedOneRepMax(100, 1)).toBeCloseTo(103.33, 2);
  });

  it("declines past fifteen reps, exactly as the server does", () => {
    // The cap is the whole point: a "PR" derived from a 30-rep set is noise, and a
    // client that computed one would badge a set the server never records.
    expect(estimatedOneRepMax(60, 15)).toBeGreaterThan(0);
    expect(estimatedOneRepMax(60, 16)).toBe(0);
  });

  it("declines a set that carried no load", () => {
    expect(estimatedOneRepMax(0, 8)).toBe(0);
    expect(estimatedOneRepMax(80, 0)).toBe(0);
  });
});

describe("the PR badge", () => {
  it("fires on the server's record type, not a friendlier spelling", () => {
    // The bug this exists for: matching `estimated_1rm` against a server that emits
    // `est_1rm` finds nothing, so the badge never appears and nobody reports it.
    expect(beatsRecord([record()], 90, 8)).toBe(true);
  });

  it("does not fire on a set that falls short", () => {
    expect(beatsRecord([record()], 70, 8)).toBe(false);
  });

  it("does not fire on a set that exactly equals the record", () => {
    expect(beatsRecord([record({ value: "101.33" })], 80, 8)).toBe(false);
  });

  it("prefers more reps at less weight over a heavier single", () => {
    // Eight at 80 beats one at 90. A badge that only celebrates heavier singles teaches
    // people to train for the indicator rather than the goal.
    expect(beatsRecord([record({ value: "93.00" })], 80, 8)).toBe(true);
  });

  it("ignores a superseded record", () => {
    expect(beatsRecord([record({ isCurrent: false, value: "200" })], 90, 8)).toBe(true);
  });

  it("ignores records of other kinds", () => {
    expect(beatsRecord([record({ recordType: "max_weight", value: "500" })], 90, 8)).toBe(true);
  });

  it("treats the first real set of a new exercise as a record", () => {
    expect(beatsRecord([], 60, 5)).toBe(true);
  });

  it("does not badge a first set that carried no load", () => {
    expect(beatsRecord([], 0, 0)).toBe(false);
    expect(beatsRecord([], null, 8)).toBe(false);
  });

  it("does not badge a first set past the rep cap", () => {
    // The formula declines, so there is no estimate to compare and nothing to celebrate.
    expect(beatsRecord([], 20, 40)).toBe(false);
  });

  it("stays quiet while the records are still loading", () => {
    expect(beatsRecord(undefined, 200, 1)).toBe(false);
  });
});

describe("which set wears the trophy", () => {
  function local(id: string, weightKg: number | null, reps: number | null, isCompleted = true) {
    return { id, weightKg, reps, isCompleted };
  }

  it("marks only the best set, not every set that beats the record", () => {
    // A progressive warm-up above an old record would otherwise be a row of trophies,
    // which says nothing about any of them.
    const sets = [local("a", 85, 8), local("b", 90, 8), local("c", 87.5, 8)];
    expect(recordSetId(sets, [record({ value: "101.33" })])).toBe("b");
  });

  it("marks nothing when the best set falls short", () => {
    expect(recordSetId([local("a", 70, 8)], [record({ value: "101.33" })])).toBeNull();
  });

  it("ignores sets that are still being typed", () => {
    const sets = [local("a", 85, 8), local("b", 200, 8, false)];
    expect(recordSetId(sets, [record({ value: "101.33" })])).toBe("a");
  });

  it("marks nothing when no set is complete", () => {
    expect(recordSetId([local("a", 200, 8, false)], [record()])).toBeNull();
  });

  it("marks nothing for bodyweight work, which has no estimate", () => {
    expect(recordSetId([local("a", null, 20)], [record()])).toBeNull();
  });

  it("marks the first real set of a brand-new exercise", () => {
    expect(recordSetId([local("a", 60, 5)], [])).toBe("a");
  });
});
