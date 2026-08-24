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
import { Input } from "@/components/ui/input";
import {
  MEAL_LABELS,
  MEAL_ORDER,
  type DiaryEntry,
  type MealType,
  nutritionApi,
  nutritionKeys,
} from "@/features/nutrition/api";
import { portion } from "@/features/nutrition/format";

/**
 * Correcting something already logged.
 *
 * Mistyping 200 g as 2000 g happens daily, and a diary whose only fix is delete-and-
 * retype is one people stop using. Only changed fields are sent; the server re-derives
 * the macros from the food rather than scaling the stored numbers, so correcting the
 * same entry repeatedly does not drift on rounding.
 */
export function EditEntryDialog({
  entry,
  onClose,
}: {
  entry: DiaryEntry;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [quantity, setQuantity] = useState(portion(entry.quantity));
  const [meal, setMeal] = useState<MealType>(entry.mealType);

  const amount = Number(quantity) || 0;
  const changed = amount !== Number(entry.quantity) || meal !== entry.mealType;

  const save = useMutation({
    mutationFn: () =>
      nutritionApi.editEntry(entry.id, {
        ...(amount !== Number(entry.quantity) ? { quantity: amount } : {}),
        ...(meal !== entry.mealType ? { mealType: meal } : {}),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: nutritionKeys.all });
      toast.success("Updated");
      onClose();
    },
    onError: () => toast.error("Couldn't update that"),
  });

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{entry.displayName}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <Input
            label={entry.servingId ? "Servings" : "Amount (g)"}
            autoFocus
            inputMode="decimal"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
          />

          <fieldset className="flex flex-col gap-1">
            <legend className="text-caption text-text-muted">Meal</legend>
            <div className="flex flex-wrap gap-1.5">
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
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => save.mutate()}
            disabled={!changed || amount <= 0 || save.isPending}
          >
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
