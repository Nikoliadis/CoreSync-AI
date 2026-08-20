import { api } from "@/lib/api/client";

export type RoutineExercise = {
  id: string;
  exerciseId: string;
  exerciseName?: string | null;
  position: number;
  notes: string | null;
  restSeconds: number | null;
};

export type Routine = {
  id: string;
  name: string;
  folder: string | null;
  notes: string | null;
  isTemplate: boolean;
  estimatedMinutes: number | null;
  version: number;
  lastPerformedAt: string | null;
  exercises: RoutineExercise[];
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

  detail: (id: string) => api.get<Routine>(`/v1/workouts/routines/${id}`),

  create: (input: { name: string; folder?: string | null; notes?: string | null }) =>
    api.post<Routine>("/v1/workouts/routines", input),

  /**
   * Adopting a template **copies** it. The author editing their template afterwards
   * never mutates someone else's plan (docs/03 §6).
   */
  adopt: (templateId: string) =>
    api.post<Routine>(`/v1/workouts/routines/templates/${templateId}/adopt`, {}),

  update: (id: string, input: { name?: string; folder?: string | null; notes?: string | null }) =>
    api.patch<Routine>(`/v1/workouts/routines/${id}`, input),

  remove: (id: string) => api.delete<void>(`/v1/workouts/routines/${id}`),
};

/**
 * Groups routines by folder for display, with unfiled ones last.
 *
 * Pulled out of the component so the ordering rule is testable: "unfiled last" is a
 * decision, not an accident of however the API happened to sort.
 */
export function groupByFolder(routines: Routine[]): [string, Routine[]][] {
  const groups = new Map<string, Routine[]>();
  for (const routine of routines) {
    const key = routine.folder ?? "";
    const bucket = groups.get(key);
    if (bucket) bucket.push(routine);
    else groups.set(key, [routine]);
  }

  return [...groups.entries()].sort(([a], [b]) => {
    if (a === "") return 1;
    if (b === "") return -1;
    return a.localeCompare(b);
  });
}
