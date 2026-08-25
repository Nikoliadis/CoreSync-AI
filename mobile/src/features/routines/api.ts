import { api } from "@/lib/api/client";

/**
 * Routines — the plans a workout is started from.
 *
 * Read-mostly, and read far more often than written: people build a routine once and run
 * it for months. That shape is why this caches the list but does not queue its writes.
 * Creating a routine offline would need client-minted ids the way sessions have them, and
 * the routine endpoints mint server-side, so a replayed create makes a second routine
 * rather than reconciling with the first. Editing plans is a thing people do at a desk;
 * running them is what happens in a basement, and that path is fully offline.
 */

export type RoutineSet = {
  id: string;
  setNumber: number;
  setType: string;
  targetRepsMin: number | null;
  targetRepsMax: number | null;
  targetWeightKg: string | null;
  targetDurationSeconds: number | null;
  targetDistanceM: string | null;
  targetRpe: string | null;
};

export type RoutineExercise = {
  id: string;
  exerciseId: string;
  exerciseName: string | null;
  position: number;
  supersetGroup: string | null;
  restSeconds: number | null;
  notes: string | null;
  sets: RoutineSet[];
};

export type Routine = {
  id: string;
  name: string;
  folder: string | null;
  notes: string | null;
  isTemplate: boolean;
  estimatedMinutes: number | null;
  /** Optimistic lock. Send it back on edit to be told about a conflict. */
  version: number;
  lastPerformedAt: string | null;
  totalSets: number;
  exercises: RoutineExercise[];
};

/** What the create and replace endpoints accept. Ids are the server's to mint. */
export type RoutineExerciseInput = {
  exerciseId: string;
  restSeconds?: number | null;
  notes?: string | null;
  sets: {
    setType?: string;
    targetRepsMin?: number | null;
    targetRepsMax?: number | null;
    targetWeightKg?: string | null;
  }[];
};

export const routineKeys = {
  all: ["routines"] as const,
  list: () => [...routineKeys.all, "list"] as const,
  templates: () => [...routineKeys.all, "templates"] as const,
  detail: (id: string) => [...routineKeys.all, id] as const,
};

export const routinesApi = {
  list: () => api.get<Routine[]>("/v1/workouts/routines"),

  templates: () => api.get<Routine[]>("/v1/workouts/routines/templates"),

  get: (id: string) => api.get<Routine>(`/v1/workouts/routines/${id}`),

  create: (input: {
    name: string;
    folder?: string | null;
    notes?: string | null;
    estimatedMinutes?: number | null;
    exercises: RoutineExerciseInput[];
  }) => api.post<Routine>("/v1/workouts/routines", input),

  update: (
    id: string,
    changes: {
      name?: string;
      folder?: string | null;
      notes?: string | null;
      estimatedMinutes?: number | null;
      /** The version that was read. Omitting it forces the write. */
      version?: number;
    },
  ) => api.patch<Routine>(`/v1/workouts/routines/${id}`, changes),

  replaceExercises: (id: string, exercises: RoutineExerciseInput[]) =>
    api.put<Routine>(`/v1/workouts/routines/${id}/exercises`, { exercises }),

  duplicate: (id: string, name?: string) =>
    api.post<Routine>(`/v1/workouts/routines/${id}/duplicate`, name ? { name } : {}),

  adopt: (templateId: string) =>
    api.post<Routine>(`/v1/workouts/routines/templates/${templateId}/adopt`, {}),

  remove: (id: string) => api.delete<void>(`/v1/workouts/routines/${id}`),
};

/** `3 × 8–12`, or `3 × 8` when the range is a single number. Empty when unprescribed. */
export function prescription(sets: readonly RoutineSet[]): string {
  if (sets.length === 0) return "";

  const first = sets[0];
  if (!first) return "";
  const min = first.targetRepsMin;
  const max = first.targetRepsMax;
  if (min === null && max === null) return `${sets.length} sets`;

  const reps = min !== null && max !== null && min !== max ? `${min}–${max}` : `${min ?? max}`;
  return `${sets.length} × ${reps}`;
}

/** Folders in a stable order, unfoldered routines last under a null key. */
export function byFolder(routines: readonly Routine[]): [string | null, Routine[]][] {
  const groups = new Map<string | null, Routine[]>();
  for (const routine of routines) {
    const key = routine.folder ?? null;
    const bucket = groups.get(key);
    if (bucket) bucket.push(routine);
    else groups.set(key, [routine]);
  }

  return [...groups.entries()].sort(([a], [b]) => {
    // Unfoldered last: a folder is a deliberate act of organisation and earns the top.
    if (a === null) return 1;
    if (b === null) return -1;
    return a.localeCompare(b);
  });
}
