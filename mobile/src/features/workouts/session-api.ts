import { api } from "@/lib/api/client";

/** One finished workout, read from the server. */

export type SessionSet = {
  id: string;
  sessionExerciseId: string;
  setNumber: number;
  setType: string;
  reps: number | null;
  weightKg: string | null;
  rpe: string | null;
  isCompleted: boolean;
  estimatedOneRepMax: string | null;
};

export type SessionExercise = {
  id: string;
  exerciseId: string;
  exerciseName: string | null;
  loggingType: string | null;
  position: number;
  restSeconds: number | null;
  notes: string | null;
  sets: SessionSet[];
};

export type Session = {
  id: string;
  name: string;
  routineId: string | null;
  notes: string | null;
  startedAt: string;
  completedAt: string | null;
  localDate: string;
  durationSeconds: number | null;
  totalVolumeKg: string;
  totalSets: number;
  totalReps: number;
  perceivedEffort: number | null;
  status: string;
  exercises: SessionExercise[];
};

export const sessionKeys = {
  all: ["session"] as const,
  detail: (id: string) => [...sessionKeys.all, id] as const,
};

export const sessionApi = {
  get: (id: string) => api.get<Session>(`/v1/workouts/sessions/${id}`),
};
