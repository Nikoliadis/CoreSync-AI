"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Minus, Plus, Timer, X } from "lucide-react";
import { useState } from "react";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { SetRow, type SetRowValue } from "@/features/workouts/components/set-row";
import { formatDuration, useRestTimer } from "@/features/workouts/rest-timer";
import { cn } from "@/lib/utils/cn";

type ExerciseBlock = {
  id: string;
  name: string;
  sets: SetRowValue[];
};

const DEFAULT_REST_SECONDS = 120;

/**
 * The live session logger.
 *
 * Local state for now: the session-write endpoints exist on the backend, but
 * wiring the optimistic set-logging path (docs/07 §3.3) needs the offline queue
 * and the client-generated UUIDv7 ids that make replay idempotent. Until that
 * lands, this screen is honest about being a working surface rather than a
 * persisted one.
 */
export default function ActiveWorkoutPage() {
  const [blocks, setBlocks] = useState<ExerciseBlock[]>([]);
  const timer = useRestTimer();

  function addExercise() {
    setBlocks((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        name: `Exercise ${current.length + 1}`,
        sets: [
          {
            id: crypto.randomUUID(),
            index: 1,
            kind: "normal",
            weightKg: null,
            reps: null,
            completed: false,
          },
        ],
      },
    ]);
  }

  function addSet(blockId: string) {
    setBlocks((current) =>
      current.map((block) =>
        block.id === blockId
          ? {
              ...block,
              sets: [
                ...block.sets,
                {
                  id: crypto.randomUUID(),
                  index: block.sets.length + 1,
                  kind: "normal",
                  // Prefilled from the previous set: the overwhelmingly common
                  // case is the same load again, and retyping it every set is
                  // the difference between a fast logger and an annoying one.
                  weightKg: block.sets.at(-1)?.weightKg ?? null,
                  reps: block.sets.at(-1)?.reps ?? null,
                  completed: false,
                },
              ],
            }
          : block,
      ),
    );
  }

  function updateSet(blockId: string, setId: string, next: Partial<SetRowValue>) {
    setBlocks((current) =>
      current.map((block) =>
        block.id === blockId
          ? { ...block, sets: block.sets.map((s) => (s.id === setId ? { ...s, ...next } : s)) }
          : block,
      ),
    );
  }

  function toggleComplete(blockId: string, setId: string) {
    let nowComplete = false;
    setBlocks((current) =>
      current.map((block) =>
        block.id === blockId
          ? {
              ...block,
              sets: block.sets.map((s) => {
                if (s.id !== setId) return s;
                nowComplete = !s.completed;
                return { ...s, completed: nowComplete };
              }),
            }
          : block,
      ),
    );
    // Completing a set starts the rest clock; un-completing one does not.
    if (nowComplete) timer.start(DEFAULT_REST_SECONDS);
  }

  const totalSets = blocks.reduce((sum, b) => sum + b.sets.filter((s) => s.completed).length, 0);
  const totalVolume = blocks.reduce(
    (sum, b) =>
      sum +
      b.sets
        .filter((s) => s.completed)
        .reduce((inner, s) => inner + (s.weightKg ?? 0) * (s.reps ?? 0), 0),
    0,
  );

  return (
    <>
      <TopBar title="Workout" />

      <PageShell className="pb-32">
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Card padding="sm">
            <p className="text-overline uppercase text-text-muted">Sets done</p>
            <p className="tabular mt-1 text-h2 text-text">{totalSets}</p>
          </Card>
          <Card padding="sm">
            <p className="text-overline uppercase text-text-muted">Volume</p>
            <p className="tabular mt-1 text-h2 text-text">
              {Math.round(totalVolume).toLocaleString()}
              <span className="ml-1 text-caption text-text-muted">kg</span>
            </p>
          </Card>
          <Card padding="sm" className="col-span-2 sm:col-span-1">
            <p className="text-overline uppercase text-text-muted">Exercises</p>
            <p className="tabular mt-1 text-h2 text-text">{blocks.length}</p>
          </Card>
        </div>

        {blocks.length === 0 ? (
          <EmptyState
            icon={<Timer className="h-8 w-8" />}
            title="Ready when you are"
            description="Add your first exercise and start logging sets."
            action={<Button onClick={addExercise}>Add exercise</Button>}
          />
        ) : (
          <div className="flex flex-col gap-4">
            {blocks.map((block) => (
              <Card key={block.id}>
                <CardHeader>
                  <CardTitle>{block.name}</CardTitle>
                  <button
                    type="button"
                    onClick={() => setBlocks((c) => c.filter((b) => b.id !== block.id))}
                    className="flex h-9 w-9 items-center justify-center rounded-sm text-text-muted hover:text-critical"
                    aria-label={`Remove ${block.name}`}
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
                  {block.sets.map((set) => (
                    <SetRow
                      key={set.id}
                      value={set}
                      onChange={(next) => updateSet(block.id, set.id, next)}
                      onToggleComplete={() => toggleComplete(block.id, set.id)}
                    />
                  ))}
                </div>

                <Button variant="ghost" size="sm" className="mt-2" onClick={() => addSet(block.id)}>
                  <Plus className="h-4 w-4" aria-hidden />
                  Add set
                </Button>
              </Card>
            ))}

            <Button variant="secondary" onClick={addExercise}>
              <Plus className="h-4 w-4" aria-hidden />
              Add exercise
            </Button>
          </div>
        )}
      </PageShell>

      {/* --- rest timer -------------------------------------------------- */}
      <AnimatePresence>
        {timer.isRunning && (
          <motion.div
            initial={{ y: 80, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 80, opacity: 0 }}
            transition={{ duration: 0.26, ease: [0.2, 0, 0, 1] }}
            className={cn(
              "fixed inset-x-0 z-40 mx-auto max-w-md px-4",
              // Clears the mobile tab bar; sits at the bottom on desktop too,
              // because that is where the thumb and the eye already are.
              "bottom-20 lg:bottom-6",
            )}
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
