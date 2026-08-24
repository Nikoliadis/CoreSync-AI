/**
 * The shape of a workout, and the pure functions over it.
 *
 * Deliberately free of `expo-sqlite` and every other native import. These are the rules
 * — how a set is numbered, what counts toward volume, which set to prefill from — and
 * rules that can only run inside a simulator are rules nobody tests.
 *
 * Persistence lives next door in `local-store.ts`.
 */

import { uuid7 } from "@/lib/utils/uuid7";

export type SetType = "normal" | "warmup" | "drop" | "failure";

export type LocalSet = {
  id: string;
  sessionExerciseId: string;
  setNumber: number;
  setType: SetType;
  reps: number | null;
  weightKg: number | null;
  rpe: number | null;
  isCompleted: boolean;
  completedAt: string | null;
};

export type LocalExercise = {
  id: string;
  exerciseId: string;
  exerciseName: string;
  position: number;
  notes: string | null;
  restSeconds: number | null;
  sets: LocalSet[];
};

export type LocalSession = {
  id: string;
  name: string;
  routineId: string | null;
  startedAt: string;
  completedAt: string | null;
  notes: string | null;
  exercises: LocalExercise[];
};


// ------------------------------------------------------------------ builders
export function newSession(input: {
  name: string;
  routineId?: string | null;
}): LocalSession {
  return {
    // Minted here, and this is the id the server will use too. That is what makes a
    // replayed flush one session rather than two.
    id: uuid7(),
    name: input.name,
    routineId: input.routineId ?? null,
    startedAt: new Date().toISOString(),
    completedAt: null,
    notes: null,
    exercises: [],
  };
}

export function newExercise(input: {
  exerciseId: string;
  exerciseName: string;
  position: number;
  restSeconds?: number | null;
}): LocalExercise {
  return {
    id: uuid7(),
    exerciseId: input.exerciseId,
    exerciseName: input.exerciseName,
    position: input.position,
    notes: null,
    restSeconds: input.restSeconds ?? null,
    sets: [],
  };
}

export function newSet(input: {
  sessionExerciseId: string;
  setNumber: number;
  setType?: SetType;
  reps?: number | null;
  weightKg?: number | null;
}): LocalSet {
  return {
    id: uuid7(),
    sessionExerciseId: input.sessionExerciseId,
    setNumber: input.setNumber,
    setType: input.setType ?? "normal",
    reps: input.reps ?? null,
    weightKg: input.weightKg ?? null,
    rpe: null,
    isCompleted: false,
    completedAt: null,
  };
}

// ------------------------------------------------------------------ derived
/**
 * Tonnage: the sum of weight times reps over completed sets.
 *
 * Only completed ones count. A set that has been typed but not ticked is an intention,
 * and counting it would make the number jump around while somebody is still deciding
 * what they are about to lift.
 */
export function sessionVolume(session: LocalSession): number {
  let total = 0;
  for (const exercise of session.exercises) {
    for (const set of exercise.sets) {
      if (set.isCompleted && set.weightKg && set.reps) {
        total += set.weightKg * set.reps;
      }
    }
  }
  return Math.round(total);
}

export function completedSetCount(session: LocalSession): number {
  return session.exercises.reduce(
    (count, exercise) => count + exercise.sets.filter((set) => set.isCompleted).length,
    0,
  );
}

/**
 * The set to prefill from when adding another.
 *
 * People rarely change weight between sets, so carrying the last one forward removes
 * the most repeated interaction in the app. Falls back to the last set of any kind so
 * the very first tick still prefills.
 */
export function lastCompletedSet(exercise: LocalExercise): LocalSet | null {
  for (let index = exercise.sets.length - 1; index >= 0; index -= 1) {
    const set = exercise.sets[index];
    if (set?.isCompleted) return set;
  }
  return exercise.sets[exercise.sets.length - 1] ?? null;
}
