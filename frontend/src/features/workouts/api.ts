import { api } from "@/lib/api/client";

export type SetType = "normal" | "warmup" | "drop" | "failure";

export type SessionSet = {
  id: string;
  sessionExerciseId: string;
  setNumber: number;
  setType: SetType;
  reps: number | null;
  weightKg: string | null;
  rpe: string | null;
  isCompleted: boolean;
  estimatedOneRepMax: string | null;
};

export type SessionExercise = {
  id: string;
  exerciseId: string;
  exerciseName: string;
  position: number;
  notes: string | null;
  restSeconds: number | null;
  supersetGroup: string | null;
  loggingType: string | null;
  sets: SessionSet[];
};

export type WorkoutSession = {
  id: string;
  name: string;
  status: string;
  localDate: string;
  startedAt: string;
  completedAt: string | null;
  totalVolumeKg: string;
  totalSets: number;
  durationSeconds: number;
  exercises: SessionExercise[];
};

export type LogSetInput = {
  /** Minted on the client so a replayed flush is one row, not two. */
  id: string;
  setType?: SetType;
  reps?: number | null;
  weightKg?: number | null;
  rpe?: number | null;
  isCompleted?: boolean;
};

export const workoutKeys = {
  all: ["workouts"] as const,
  active: () => [...workoutKeys.all, "active"] as const,
  session: (id: string) => [...workoutKeys.all, "session", id] as const,
  history: () => [...workoutKeys.all, "history"] as const,
};

export const workoutsApi = {
  /** Returns null rather than throwing when nothing is in progress. */
  active: async (): Promise<WorkoutSession | null> => {
    try {
      return await api.get<WorkoutSession>("/v1/workouts/sessions/active");
    } catch {
      return null;
    }
  },

  session: (id: string) => api.get<WorkoutSession>(`/v1/workouts/sessions/${id}`),

  start: (input: { clientSessionId: string; name?: string; routineId?: string }) =>
    api.post<WorkoutSession>("/v1/workouts/sessions", input),

  addExercise: (sessionId: string, exerciseId: string) =>
    api.post<SessionExercise>(`/v1/workouts/sessions/${sessionId}/exercises`, { exerciseId }),

  removeExercise: (sessionId: string, sessionExerciseId: string) =>
    api.delete<void>(`/v1/workouts/sessions/${sessionId}/exercises/${sessionExerciseId}`),

  logSet: (sessionId: string, sessionExerciseId: string, input: LogSetInput) =>
    api.post<SessionSet>(
      `/v1/workouts/sessions/${sessionId}/exercises/${sessionExerciseId}/sets`,
      input,
    ),

  // Sets are addressed through their exercise, not the session directly — a set id
  // alone would not tell the server which exercise's ordering to renumber.
  updateSet: (
    sessionId: string,
    sessionExerciseId: string,
    setId: string,
    input: Partial<LogSetInput>,
  ) =>
    api.patch<SessionSet>(
      `/v1/workouts/sessions/${sessionId}/exercises/${sessionExerciseId}/sets/${setId}`,
      input,
    ),

  deleteSet: (sessionId: string, sessionExerciseId: string, setId: string) =>
    api.delete<void>(
      `/v1/workouts/sessions/${sessionId}/exercises/${sessionExerciseId}/sets/${setId}`,
    ),

  complete: (sessionId: string) =>
    api.post<WorkoutSession>(`/v1/workouts/sessions/${sessionId}/complete`, {}),

  discard: (sessionId: string) =>
    api.post<void>(`/v1/workouts/sessions/${sessionId}/discard`, {}),
};
