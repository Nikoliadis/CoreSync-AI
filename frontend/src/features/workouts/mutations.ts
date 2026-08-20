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
import { enqueue } from "@/lib/offline/sync-engine";
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
    mutationFn: async ({
      sessionExerciseId,
      input,
    }: {
      sessionExerciseId: string;
      input: LogSetInput;
    }) => {
      if (!sessionId) throw new Error("no active session");

      // Written to the log first, then sent. A set logged in a basement gym with no
      // signal is durable the moment the user taps, and the engine drains it when the
      // phone reconnects — rather than the mutation failing and the set being lost.
      await enqueue({
        opId: uuid7(),
        type: "set.log",
        at: new Date().toISOString(),
        payload: { sessionId, sessionExerciseId, ...input },
      });
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
      // Only reached if the *log itself* failed — storage denied, quota exhausted. A
      // network failure never lands here, because the durable write already succeeded.
      if (context?.previous) {
        queryClient.setQueryData(workoutKeys.active(), context.previous);
      }
      toast.error("Set not saved", { description: "Storage is unavailable on this device." });
    },

    onSuccess: (_result, { sessionExerciseId, input }) => {
      // The row is durable once it is in the log, so `pending` is cleared here rather
      // than waiting for the server. The estimated 1RM stays null until the next read
      // of the session — the client cannot compute it, and inventing one would put a
      // number on screen that no server ever agreed to.
      replaceSession(queryClient, (session) => ({
        ...session,
        exercises: session.exercises.map((exercise) =>
          exercise.id === sessionExerciseId
            ? {
                ...exercise,
                sets: exercise.sets.map((s) =>
                  s.id === input.id ? ({ ...s, pending: false } as PendingSet) : s,
                ),
              }
            : exercise,
        ),
      }));
    },

    // No retry, and no invalidation. The log *is* the retry, and retrying the enqueue
    // would write the same set several times under different operation ids. A refetch
    // mid-workout would also stall the UI on exactly the connection that cannot afford
    // it, and the optimistic state is already correct.
    retry: false,
  });
}

export function useUpdateSet(sessionId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      sessionExerciseId,
      setId,
      input,
    }: {
      sessionExerciseId: string;
      setId: string;
      input: Partial<LogSetInput>;
    }) => {
      if (!sessionId) throw new Error("no active session");

      // Through the log for the same reason as logging: ticking a set complete is the
      // most frequent action in a session, and the log preserves order, so an update
      // can never overtake the `set.log` that created the row.
      await enqueue({
        opId: uuid7(),
        type: "set.update",
        at: new Date().toISOString(),
        payload: { sessionId, sessionExerciseId, setId, ...input },
      });
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
      toast.error("Change not saved", { description: "Storage is unavailable on this device." });
    },

    // As with logging: the log is the retry.
    retry: false,
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
