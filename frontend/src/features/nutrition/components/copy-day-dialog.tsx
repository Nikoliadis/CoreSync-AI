"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  MEAL_LABELS,
  MEAL_ORDER,
  type MealType,
  nutritionApi,
  nutritionKeys,
} from "@/features/nutrition/api";
import { friendlyDate, localToday, shiftDate } from "@/features/nutrition/format";

/**
 * Copy yesterday onto today, or one meal of it.
 *
 * People eat the same breakfast most days. Re-logging it item by item is the friction
 * that decides whether a diary survives its second week.
 */
export function CopyDayDialog({
  targetDate,
  onClose,
}: {
  targetDate: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [source, setSource] = useState(() => shiftDate(targetDate, -1));
  const [meal, setMeal] = useState<MealType | null>(null);

  const copy = useMutation({
    mutationFn: () =>
      nutritionApi.copyDay({
        sourceDate: source,
        targetDate,
        ...(meal ? { mealType: meal } : {}),
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: nutritionKeys.all });
      toast.success(
        `Copied ${result.copied} ${result.copied === 1 ? "entry" : "entries"}`,
      );
      onClose();
    },
    onError: () =>
      toast.error("Nothing to copy", {
        description: "There was nothing logged on that day.",
      }),
  });

  // Only the last week: copying from three months ago is not a thing anyone does, and
  // an unbounded date picker is a worse way to choose "yesterday".
  const candidates = Array.from({ length: 7 }, (_, offset) =>
    shiftDate(targetDate, -(offset + 1)),
  ).filter((iso) => iso <= localToday());

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Copy onto {friendlyDate(targetDate).toLowerCase()}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <fieldset className="flex flex-col gap-1">
            <legend className="text-caption text-text-muted">Copy from</legend>
            <div className="flex flex-wrap gap-1.5">
              {candidates.map((iso) => (
                <button
                  key={iso}
                  type="button"
                  aria-pressed={source === iso}
                  onClick={() => setSource(iso)}
                  className={
                    source === iso
                      ? "rounded-full border border-accent bg-accent/10 px-3 py-1.5 text-caption text-text"
                      : "rounded-full border border-border px-3 py-1.5 text-caption text-text-secondary transition-colors hover:bg-surface-well"
                  }
                >
                  {friendlyDate(iso)}
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset className="flex flex-col gap-1">
            <legend className="text-caption text-text-muted">What</legend>
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                aria-pressed={meal === null}
                onClick={() => setMeal(null)}
                className={
                  meal === null
                    ? "rounded-full border border-accent bg-accent/10 px-3 py-1.5 text-caption text-text"
                    : "rounded-full border border-border px-3 py-1.5 text-caption text-text-secondary transition-colors hover:bg-surface-well"
                }
              >
                Whole day
              </button>
              {MEAL_ORDER.map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={meal === option}
                  onClick={() => setMeal(option)}
                  className={
                    meal === option
                      ? "rounded-full border border-accent bg-accent/10 px-3 py-1.5 text-caption text-text"
                      : "rounded-full border border-border px-3 py-1.5 text-caption text-text-secondary transition-colors hover:bg-surface-well"
                  }
                >
                  {MEAL_LABELS[option]}
                </button>
              ))}
            </div>
          </fieldset>

          <p className="text-caption text-text-muted">
            The numbers are copied exactly as they were logged, not recalculated.
          </p>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => copy.mutate()} disabled={copy.isPending}>
            {copy.isPending ? "Copying…" : "Copy"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
