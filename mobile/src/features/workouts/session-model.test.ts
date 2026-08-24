import { describe, expect, it } from "vitest";

import {
  completedSetCount,
  lastCompletedSet,
  newExercise,
  newSession,
  newSet,
  sessionVolume,
  type LocalExercise,
  type LocalSet,
} from "./session-model";

function set(overrides: Partial<LocalSet> = {}): LocalSet {
  return {
    id: "s",
    sessionExerciseId: "ex",
    setNumber: 1,
    setType: "normal",
    reps: 8,
    weightKg: 80,
    rpe: null,
    isCompleted: true,
    completedAt: null,
    ...overrides,
  };
}

function exercise(sets: LocalSet[]): LocalExercise {
  return {
    id: "ex",
    exerciseId: "bench",
    exerciseName: "Bench Press",
    position: 0,
    notes: null,
    restSeconds: null,
    sets,
  };
}

describe("volume", () => {
  it("is weight times reps over completed sets", () => {
    const session = { ...newSession({ name: "x" }), exercises: [exercise([set(), set()])] };
    expect(sessionVolume(session)).toBe(80 * 8 * 2);
  });

  it("ignores sets that were typed but never ticked", () => {
    // A set on screen is an intention. Counting it would make the number jump around
    // while somebody is still deciding what they are about to lift.
    const session = {
      ...newSession({ name: "x" }),
      exercises: [exercise([set(), set({ isCompleted: false })])],
    };
    expect(sessionVolume(session)).toBe(80 * 8);
  });

  it("ignores a set with no weight", () => {
    // Bodyweight work has reps and no load. Treating a null as zero is right here —
    // it contributes nothing to tonnage — but it must not produce NaN.
    const session = {
      ...newSession({ name: "x" }),
      exercises: [exercise([set({ weightKg: null })])],
    };
    expect(sessionVolume(session)).toBe(0);
  });

  it("is zero for an empty session", () => {
    expect(sessionVolume(newSession({ name: "x" }))).toBe(0);
  });
});

describe("completed set count", () => {
  it("counts only ticked sets across every exercise", () => {
    const session = {
      ...newSession({ name: "x" }),
      exercises: [
        exercise([set(), set({ isCompleted: false })]),
        exercise([set(), set()]),
      ],
    };
    expect(completedSetCount(session)).toBe(3);
  });
});

describe("prefill source", () => {
  it("is the last completed set", () => {
    const found = lastCompletedSet(
      exercise([set({ id: "a" }), set({ id: "b" }), set({ id: "c", isCompleted: false })]),
    );
    expect(found?.id).toBe("b");
  });

  it("falls back to the last set of any kind", () => {
    // So the very first row still prefills once something has been typed into it.
    const found = lastCompletedSet(
      exercise([set({ id: "a", isCompleted: false })]),
    );
    expect(found?.id).toBe("a");
  });

  it("is null for an exercise with no sets", () => {
    expect(lastCompletedSet(exercise([]))).toBeNull();
  });
});

describe("ids", () => {
  it("are distinct per entity", () => {
    // Every one becomes a server primary key, so a collision is a lost set.
    const ids = new Set([
      newSession({ name: "a" }).id,
      newExercise({ exerciseId: "e", exerciseName: "E", position: 0 }).id,
      newSet({ sessionExerciseId: "ex", setNumber: 1 }).id,
    ]);
    expect(ids.size).toBe(3);
  });
});
