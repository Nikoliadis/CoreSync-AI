import { describe, expect, it } from "vitest";

import {
  completedSetCount,
  elapsedSeconds,
  formatElapsed,
  lastCompletedSet,
  newExercise,
  newSession,
  newSet,
  sessionVolume,
  type LocalExercise,
  type LocalSession,
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

describe("the session clock", () => {
  function at(minutes: number): string {
    return new Date(Date.UTC(2026, 7, 25, 18, minutes, 0)).toISOString();
  }
  const now = Date.UTC(2026, 7, 25, 18, 45, 0);

  function running(overrides: Partial<LocalSession> = {}): LocalSession {
    return { ...newSession({ name: "Push" }), startedAt: at(0), ...overrides };
  }

  it("counts wall-clock time when nothing was paused", () => {
    expect(elapsedSeconds(running(), now)).toBe(45 * 60);
  });

  it("subtracts time already banked from earlier pauses", () => {
    expect(elapsedSeconds(running({ pausedSeconds: 10 * 60 }), now)).toBe(35 * 60);
  });

  it("freezes while a pause is still open", () => {
    // Paused at 18:30, read at 18:45: the clock shows 30 minutes, not 45.
    expect(elapsedSeconds(running({ pausedAt: at(30) }), now)).toBe(30 * 60);
  });

  it("adds up several pauses", () => {
    const session = running({ pausedSeconds: 5 * 60, pausedAt: at(40) });
    expect(elapsedSeconds(session, now)).toBe(35 * 60);
  });

  it("stops at completion rather than running forever", () => {
    const session = running({ completedAt: at(40) });
    expect(elapsedSeconds(session, now)).toBe(40 * 60);
  });

  it("survives a session stored before pausing existed", () => {
    // Sitting mid-workout in SQLite when the app updated. `NaN` on the header would be
    // the first thing that user saw.
    const legacy: Partial<LocalSession> = { ...running() };
    delete legacy.pausedSeconds;
    delete legacy.pausedAt;

    expect(elapsedSeconds(legacy as LocalSession, now)).toBe(45 * 60);
  });

  it("never goes negative on a phone whose clock moved", () => {
    expect(elapsedSeconds(running({ pausedSeconds: 60 * 60 }), now)).toBe(0);
  });

  it("formats below and above an hour", () => {
    expect(formatElapsed(4 * 60 + 12)).toBe("4:12");
    expect(formatElapsed(3600 + 4 * 60 + 12)).toBe("1:04:12");
    expect(formatElapsed(0)).toBe("0:00");
  });
});
