"use client";

import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Minus, Plus, Timer, Trash2, X } from "lucide-react";
import { useState } from "react";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { SessionExercise } from "@/features/workouts/api";
import { ExercisePicker } from "@/features/workouts/components/exercise-picker";
import { SetRow } from "@/features/workouts/components/set-row";
import {
  useActiveSession,
  useAddExercise,
  useCompleteSession,
  useDiscardSession,
  useLogSet,
  useRemoveExercise,
  useUpdateSet,
  type PendingSet,
} from "@/features/workouts/mutations";
import { useStartSession } from "@/features/workouts/mutations";
import { formatDuration, useRestTimer } from "@/features/workouts/rest-timer";
import { uuid7 } from "@/lib/utils/uuid7";
import { cn } from "@/lib/utils/cn";

const DEFAULT_REST_SECONDS = 120;

export default function ActiveWorkoutPage() {
  const session = useActiveSession();
  const sessionId = session.data?.id;

  const start = useStartSession();
  const addExercise = useAddExercise(sessionId);
  const removeExercise = useRemoveExercise(sessionId);
  const logSet = useLogSet(sessionId);
  const updateSet = useUpdateSet(sessionId);
  const complete = useCompleteSession(sessionId);
  const discard = useDiscardSession(sessionId);

  const [pickerOpen, setPickerOpen] = useState(false);
  const timer = useRestTimer();

  if (session.isLoading) {
    return (
      <>
        <TopBar title="Workout" />
        <PageShell>
          <div className="flex flex-col gap-4">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-48 w-full" />
          </div>
        </PageShell>
      </>
    );
  }

  // --- nothing in progress ------------------------------------------------
  if (!session.data) {
    return (
      <>
        <TopBar title="Workout" />
        <PageShell>
          <EmptyState
            icon={<Timer className="h-8 w-8" />}
            title="Ready when you are"
            description="Start a session and log your sets as you go. Everything saves as you tap."
            action={
              <Button onClick={() => start.mutate({})} loading={start.isPending}>
                Start a workout
              </Button>
            }
          />
        </PageShell>
      </>
    );
  }

  const workout = session.data;

  function logNextSet(exercise: SessionExercise) {
    const previous = exercise.sets.at(-1);
    logSet.mutate({
      sessionExerciseId: exercise.id,
      input: {
        // Minted here, before the request — this is what makes a retry idempotent.
        id: uuid7(),
        setType: "normal",
        // Carried forward from the last set: the common case is the same load again,
        // and retyping it every time is the difference between a fast logger and an
        // irritating one.
        reps: previous?.reps ?? null,
        weightKg: previous?.weightKg ? Number(previous.weightKg) : null,
        isCompleted: false,
      },
    });
  }

  return (
    <>
      <TopBar
        title="Workout"
        action={
          <Button size="sm" onClick={() => complete.mutate()} loading={complete.isPending}>
            <CheckCircle2 className="h-4 w-4" aria-hidden />
            Finish
          </Button>
        }
      />

      <PageShell className="pb-32">
        <div className="mb-4 grid grid-cols-3 gap-3">
          <Card padding="sm">
            <p className="text-overline uppercase text-text-muted">Sets</p>
            <p className="tabular mt-1 text-h2 text-text">{workout.totalSets}</p>
          </Card>
          <Card padding="sm">
            <p className="text-overline uppercase text-text-muted">Volume</p>
            <p className="tabular mt-1 text-h2 text-text">
              {Math.round(Number(workout.totalVolumeKg)).toLocaleString()}
              <span className="ml-1 text-caption text-text-muted">kg</span>
            </p>
          </Card>
          <Card padding="sm">
            <p className="text-overline uppercase text-text-muted">Exercises</p>
            <p className="tabular mt-1 text-h2 text-text">{workout.exercises.length}</p>
          </Card>
        </div>

        {workout.exercises.length === 0 ? (
          <EmptyState
            icon={<Plus className="h-8 w-8" />}
            title="Add your first exercise"
            description="Search the catalogue and start logging."
            action={<Button onClick={() => setPickerOpen(true)}>Add exercise</Button>}
          />
        ) : (
          <div className="flex flex-col gap-4">
            {workout.exercises.map((exercise) => (
              <Card key={exercise.id}>
                <CardHeader>
                  <CardTitle>{exercise.exerciseName}</CardTitle>
                  <button
                    type="button"
                    onClick={() => removeExercise.mutate(exercise.id)}
                    className="flex h-9 w-9 items-center justify-center rounded-sm text-text-muted hover:text-critical"
                    aria-label={`Remove ${exercise.exerciseName}`}
                  >
                    <X className="h-4 w-4" aria-hidden />
                  </button>
                </CardHeader>

                <div className="grid grid-cols-[2.5rem_1fr_1fr_3rem] gap-2 px-2 pb-1">
                  <span className="text-overline uppercase text-text-muted">Set</span>
                  <span className="text-center text-overline uppercase text-text-muted">kg</span>
                  <span className="text-center text-overline uppercase text-text-muted">Reps</span>
                  <span />
                </div>

                <div className="flex flex-col gap-1">
                  {exercise.sets.map((set) => {
                    const pending = (set as PendingSet).pending === true;
                    return (
                      <div
                        key={set.id}
                        // Unsaved rows are dimmed rather than hidden or blocked: the
                        // number is real, it just has not reached the server yet.
                        className={cn(pending && "opacity-60")}
                        aria-busy={pending || undefined}
                      >
                        <SetRow
                          value={{
                            id: set.id,
                            index: set.setNumber,
                            kind: set.setType,
                            weightKg: set.weightKg === null ? null : Number(set.weightKg),
                            reps: set.reps,
                            completed: set.isCompleted,
                          }}
                          onChange={(next) =>
                            updateSet.mutate({
                              sessionExerciseId: exercise.id,
                              setId: set.id,
                              input: {
                                reps: next.reps,
                                weightKg: next.weightKg,
                              },
                            })
                          }
                          onToggleComplete={() => {
                            const nowComplete = !set.isCompleted;
                            updateSet.mutate({
                              sessionExerciseId: exercise.id,
                              setId: set.id,
                              input: { isCompleted: nowComplete },
                            });
                            if (nowComplete) timer.start(DEFAULT_REST_SECONDS);
                          }}
                        />
                      </div>
                    );
                  })}
                </div>

                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-2"
                  onClick={() => logNextSet(exercise)}
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  Add set
                </Button>
              </Card>
            ))}

            <Button variant="secondary" onClick={() => setPickerOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden />
              Add exercise
            </Button>

            <Button
              variant="ghost"
              className="text-text-muted hover:text-critical"
              onClick={() => discard.mutate()}
              loading={discard.isPending}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
              Discard workout
            </Button>
          </div>
        )}
      </PageShell>

      <ExercisePicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        onPick={(exerciseId) => addExercise.mutate(exerciseId)}
      />

      {/* --- rest timer -------------------------------------------------- */}
      <AnimatePresence>
        {timer.isRunning && (
          <motion.div
            initial={{ y: 80, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 80, opacity: 0 }}
            transition={{ duration: 0.26, ease: [0.2, 0, 0, 1] }}
            className="fixed inset-x-0 bottom-20 z-40 mx-auto max-w-md px-4 lg:bottom-6"
          >
            <div className="flex items-center gap-3 rounded-lg border border-border bg-surface-raised p-3 shadow-e3">
              <Timer className="h-5 w-5 shrink-0 text-accent-text" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-overline uppercase text-text-muted">Rest</p>
                <p className="tabular text-h2 text-text" aria-live="polite">
                  {formatDuration(timer.remaining)}
                </p>
              </div>
              <div className="flex gap-1">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => timer.add(-15)}
                  aria-label="Subtract 15 seconds"
                >
                  <Minus className="h-4 w-4" aria-hidden />
                  15s
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => timer.add(15)}
                  aria-label="Add 15 seconds"
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  15s
                </Button>
                <Button variant="ghost" size="icon" onClick={timer.stop} aria-label="Skip rest">
                  <X className="h-4 w-4" aria-hidden />
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
