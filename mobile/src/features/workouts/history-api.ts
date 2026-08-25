import { api } from "@/lib/api/client";

/**
 * What you did last time, and what your best is.
 *
 * This is the single most valuable thing on the workout screen and the reason people
 * open a logging app between sets — not to record the past set, but to know what to put
 * on the bar for the next one. An empty "PREV" column is a column that earns nothing.
 *
 * Read-only, so unlike the diary it caches cleanly: the last session for an exercise is
 * a fact that does not change while you are training.
 */

export type HistorySet = {
  id: string;
  setNumber: number;
  setType: string;
  reps: number | null;
  weightKg: string | null;
  rpe: string | null;
  isCompleted: boolean;
  estimatedOneRepMax: string | null;
};

export type HistorySession = {
  sessionId: string;
  sessionName: string;
  localDate: string;
  totalVolumeKg: string;
  bestSetId: string | null;
  sets: HistorySet[];
};

export type ExerciseHistory = {
  exerciseId: string;
  exerciseName: string;
  totalSessions: number;
  totalSets: number;
  totalVolumeKg: string;
  bestEstimatedOneRepMax: string | null;
  lastPerformedOn: string | null;
  sessions: HistorySession[];
};

export type PersonalRecord = {
  id: string;
  exerciseId: string;
  exerciseName: string | null;
  /** `weight` | `volume` | `estimated_1rm` | `reps` — the server's vocabulary. */
  recordType: string;
  value: string;
  repsAtValue: number | null;
  achievedOn: string;
  isCurrent: boolean;
  previousValue: string | null;
  improvement: string | null;
};

export const historyKeys = {
  all: ["exercise-history"] as const,
  history: (exerciseId: string) => [...historyKeys.all, exerciseId] as const,
  records: (exerciseId: string) => [...historyKeys.all, exerciseId, "records"] as const,
};

export const historyApi = {
  forExercise: (exerciseId: string) =>
    api.get<ExerciseHistory>(`/v1/exercises/${exerciseId}/history`, {
      // One session is all the workout screen shows. Asking for a year of history to
      // render a single "PREV" column would be a large payload between every set.
      query: { limit: 1 },
    }),

  records: (exerciseId: string) =>
    api.get<PersonalRecord[]>(`/v1/exercises/${exerciseId}/records`),
};

/**
 * The set from the previous session that matches this set number.
 *
 * Matched by number rather than by best set: the point is "what did I do for set 3 last
 * time", not "what is my best ever". Falls back to the last set of that session when the
 * previous workout was shorter, which is more useful than showing nothing.
 */
export function previousSet(
  history: ExerciseHistory | undefined,
  setNumber: number,
): HistorySet | null {
  const session = history?.sessions[0];
  if (!session || session.sets.length === 0) return null;

  const exact = session.sets.find((set) => set.setNumber === setNumber);
  return exact ?? session.sets[session.sets.length - 1] ?? null;
}

/** `80 × 8`, or null when the set carried no load — bodyweight work, or a blank row. */
export function formatPrevious(set: HistorySet | null): string | null {
  if (!set) return null;
  if (set.weightKg && set.reps) return `${trim(set.weightKg)} × ${set.reps}`;
  if (set.reps) return `${set.reps} reps`;
  return null;
}

/**
 * Whether a set beats the standing record.
 *
 * Deliberately compares against the estimated 1RM rather than raw weight: eight reps at
 * 80 kg beats one rep at 90, and a product that only celebrates heavier singles teaches
 * people to train for the indicator rather than the goal.
 *
 * Epley, matching `PersonalRecordDetector` on the server. Reproducing the formula here
 * means the badge appears the moment a set is ticked rather than after a sync.
 */
export function estimatedOneRepMax(weightKg: number, reps: number): number {
  if (weightKg <= 0 || reps <= 0) return 0;
  // Capped at 15, exactly as `estimated_one_rep_max` on the server and the generated
  // column behind it. Epley diverges badly past that, and a "PR" derived from a 30-rep
  // set is noise dressed as progress. Diverging here would make the badge disagree with
  // the record the server actually stores.
  if (reps > 15) return 0;
  // Quantized to 2dp because the server stores it that way. Comparing an unrounded
  // 101.33333 against a stored 101.33 makes every repeat of your best set a new record,
  // so the trophy would appear on a set that matched rather than beat it.
  return Math.round(weightKg * (1 + reps / 30) * 100) / 100;
}

export function beatsRecord(
  records: readonly PersonalRecord[] | undefined,
  weightKg: number | null,
  reps: number | null,
): boolean {
  if (!records || !weightKg || !reps) return false;

  // `est_1rm` is the server's `RecordType` value. Guessing at a friendlier spelling
  // would silently match nothing and the badge would never appear.
  const standing = records.find(
    (record) => record.recordType === "est_1rm" && record.isCurrent,
  );
  const estimate = estimatedOneRepMax(weightKg, reps);
  // Zero means the formula declined — no load, or past the rep cap. Neither is a record.
  if (estimate <= 0) return false;

  // No standing record means this is the first real set of this exercise, which is one.
  if (!standing) return true;
  return estimate > Number(standing.value);
}

function trim(value: string): string {
  const parsed = Number(value);
  return Number.isInteger(parsed) ? String(parsed) : parsed.toFixed(1);
}

/**
 * Which single set in this exercise wears the trophy.
 *
 * Not every set that beats the standing record — five progressively heavier sets all
 * beat the record you walked in with, and five trophies say nothing. The badge marks the
 * best set of the session, and only when it actually beats what came before.
 *
 * The comparison is against the record as it stood at the start, because that is what the
 * server holds: the PRs set today are not detected until the session is completed and
 * synced.
 */
export function recordSetId(
  sets: readonly {
    id: string;
    weightKg: number | null;
    reps: number | null;
    isCompleted: boolean;
  }[],
  records: readonly PersonalRecord[] | undefined,
): string | null {
  let bestId: string | null = null;
  let best = 0;

  for (const set of sets) {
    if (!set.isCompleted || !set.weightKg || !set.reps) continue;
    const estimate = estimatedOneRepMax(set.weightKg, set.reps);
    if (estimate > best) {
      best = estimate;
      bestId = set.id;
    }
  }

  if (bestId === null) return null;
  const winner = sets.find((set) => set.id === bestId);
  return winner && beatsRecord(records, winner.weightKg, winner.reps) ? bestId : null;
}
