"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  workoutKeys,
  workoutsApi,
  type LogSetInput,
  type SessionSet,
  type WorkoutSession,
} from "@/features/workouts/api";
import { uuid7 } from "@/lib/utils/uuid7";

/** A set that is on screen but not yet acknowledged by the server. */
export type PendingSet = SessionSet & { pending?: boolean };

export function useActiveSession() {
  return useQuery({
    queryKey: workoutKeys.active(),
    queryFn: workoutsApi.active,
    // The one query that must never serve a stale copy: it is the thing being edited.
    staleTime: 0,
  });
}

function replaceSession(
  queryClient: ReturnType<typeof useQueryClient>,
  update: (session: WorkoutSession) => WorkoutSession,
) {
  queryClient.setQueryData<WorkoutSession | null>(workoutKeys.active(), (old) =>
    old ? update(old) : old,
  );
}

export function useStartSession() {
  const queryClient = useQueryClient();

  return useMutation({
    // The client id makes a retried "Start workout" resolve to one session rather
    // than two — the button is tapped in a gym on a bad connection.
    mutationFn: (input: { name?: string; routineId?: string }) =>
      workoutsApi.start({ ...input, clientSessionId: uuid7() }),
    onSuccess: (session) => {
      queryClient.setQueryData(workoutKeys.active(), session);
    },
    onError: () => toast.error("Couldn't start the workout", { description: "Try again." }),
  });
}

export function useAddExercise(sessionId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (exerciseId: string) => {
      if (!sessionId) throw new Error("no active session");
      return workoutsApi.addExercise(sessionId, exerciseId);
    },
    onSuccess: (exercise) => {
      replaceSession(queryClient, (session) => ({
        ...session,
        exercises: [...session.exercises, { ...exercise, sets: exercise.sets ?? [] }],
      }));
    },
    onError: () => toast.error("Couldn't add that exercise"),
  });
}

export function useRemoveExercise(sessionId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (sessionExerciseId: string) => {
      if (!sessionId) throw new Error("no active session");
      return workoutsApi.removeExercise(sessionId, sessionExerciseId);
    },
    onSuccess: (_void, sessionExerciseId) => {
      replaceSession(queryClient, (session) => ({
        ...session,
        exercises: session.exercises.filter((e) => e.id !== sessionExerciseId),
      }));
    },
    onError: () => toast.error("Couldn't remove that exercise"),
  });
}

/**
 * Logging a set — the interaction the whole product is judged on (docs/07 §3.3).
 *
 * The row appears instantly and the network catches up. Because the id is minted on
 * the client, reconciling the server's reply is an identity match rather than a guess,
 * and a retry that the server already applied is a no-op instead of a duplicate set.
 */
export function useLogSet(sessionId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      sessionExerciseId,
      input,
    }: {
      sessionExerciseId: string;
      input: LogSetInput;
    }) => {
      if (!sessionId) throw new Error("no active session");
      return workoutsApi.logSet(sessionId, sessionExerciseId, input);
    },

    onMutate: async ({ sessionExerciseId, input }) => {
      await queryClient.cancelQueries({ queryKey: workoutKeys.active() });
      const previous = queryClient.getQueryData<WorkoutSession | null>(workoutKeys.active());

      replaceSession(queryClient, (session) => ({
        ...session,
        exercises: session.exercises.map((exercise) =>
          exercise.id === sessionExerciseId
            ? {
                ...exercise,
                sets: [
                  ...exercise.sets,
                  {
                    id: input.id,
                    sessionExerciseId,
                    setNumber: exercise.sets.length + 1,
                    setType: input.setType ?? "normal",
                    reps: input.reps ?? null,
                    weightKg: input.weightKg?.toString() ?? null,
                    rpe: null,
                    isCompleted: input.isCompleted ?? true,
                    estimatedOneRepMax: null,
                    pending: true,
                  } as PendingSet,
                ],
              }
            : exercise,
        ),
      }));

      return { previous };
    },

    onError: (_error, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(workoutKeys.active(), context.previous);
      }
      toast.error("Set not saved", { description: "Check your connection and try again." });
    },

    onSuccess: (serverSet, { sessionExerciseId }) => {
      // Swap the optimistic row for the server's, which carries the real set number
      // and the estimated 1RM the client cannot compute.
      replaceSession(queryClient, (session) => ({
        ...session,
        exercises: session.exercises.map((exercise) =>
          exercise.id === sessionExerciseId
            ? {
                ...exercise,
                sets: exercise.sets.map((s) => (s.id === serverSet.id ? serverSet : s)),
              }
            : exercise,
        ),
      }));
    },

    // Deliberately no invalidation: a refetch mid-workout stalls the UI on a gym
    // connection, and the optimistic state is already correct.
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
  });
}

export function useUpdateSet(sessionId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      sessionExerciseId,
      setId,
      input,
    }: {
      sessionExerciseId: string;
      setId: string;
      input: Partial<LogSetInput>;
    }) => {
      if (!sessionId) throw new Error("no active session");
      return workoutsApi.updateSet(sessionId, sessionExerciseId, setId, input);
    },

    onMutate: async ({ sessionExerciseId, setId, input }) => {
      await queryClient.cancelQueries({ queryKey: workoutKeys.active() });
      const previous = queryClient.getQueryData<WorkoutSession | null>(workoutKeys.active());

      replaceSession(queryClient, (session) => ({
        ...session,
        exercises: session.exercises.map((exercise) =>
          exercise.id === sessionExerciseId
            ? {
                ...exercise,
                sets: exercise.sets.map((s) =>
                  s.id === setId
                    ? {
                        ...s,
                        reps: input.reps !== undefined ? input.reps : s.reps,
                        weightKg:
                          input.weightKg !== undefined
                            ? (input.weightKg?.toString() ?? null)
                            : s.weightKg,
                        isCompleted: input.isCompleted ?? s.isCompleted,
                      }
                    : s,
                ),
              }
            : exercise,
        ),
      }));

      return { previous };
    },

    onError: (_error, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(workoutKeys.active(), context.previous);
      }
      toast.error("Change not saved");
    },

    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
  });
}

export function useCompleteSession(sessionId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => {
      if (!sessionId) throw new Error("no active session");
      return workoutsApi.complete(sessionId);
    },
    onSuccess: () => {
      queryClient.setQueryData(workoutKeys.active(), null);
      // History and the dashboard genuinely are stale now, so these do invalidate.
      void queryClient.invalidateQueries({ queryKey: workoutKeys.history() });
      toast.success("Workout saved");
    },
    onError: () => toast.error("Couldn't finish the workout", { description: "Try again." }),
  });
}

export function useDiscardSession(sessionId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => {
      if (!sessionId) throw new Error("no active session");
      return workoutsApi.discard(sessionId);
    },
    onSuccess: () => {
      queryClient.setQueryData(workoutKeys.active(), null);
      toast.success("Workout discarded");
    },
    onError: () => toast.error("Couldn't discard the workout"),
  });
}
