"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Droplet } from "lucide-react";
import { toast } from "sonner";

import { Card } from "@/components/ui/card";
import { ProgressRing } from "@/components/ui/progress-ring";
import { nutritionApi, nutritionKeys } from "@/features/nutrition/api";

// No undo control: the API accepts positive increments only, which is the right
// constraint — a negative amount would let a mis-tap drive the day's total below zero.
// Correcting a mis-tap needs a delete endpoint over a specific log, which does not exist
// yet; the repository method does, so it is a small addition when it is wanted.

/** A sensible daily default until hydration targets are user-configurable. */
const DAILY_GOAL_ML = 2500;
const INCREMENTS = [250, 500];

export function WaterCard({ totalMl, localDate }: { totalMl: string; localDate: string }) {
  const queryClient = useQueryClient();
  const total = Math.round(Number(totalMl));

  const log = useMutation({
    mutationFn: (millilitres: number) => nutritionApi.logWater(millilitres, localDate),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: nutritionKeys.all });
    },
    onError: () => toast.error("Couldn't log that"),
  });

  return (
    <Card className="flex items-center gap-4">
      <ProgressRing
        value={total}
        max={DAILY_GOAL_ML}
        label="Water"
        unit="ml"
        size={92}
        strokeWidth={8}
        color="var(--color-chart-2)"
      />
      <div className="min-w-0 flex-1">
        <p className="text-caption text-text-muted">
          <span className="tabular">{total}</span> of{" "}
          <span className="tabular">{DAILY_GOAL_ML}</span> ml
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {INCREMENTS.map((amount) => (
            <button
              key={amount}
              type="button"
              disabled={log.isPending}
              onClick={() => log.mutate(amount)}
              className="flex items-center gap-1 rounded-full border border-border px-3 py-1.5 text-caption text-text-secondary transition-colors hover:bg-surface-well disabled:opacity-50"
            >
              <Droplet className="h-3.5 w-3.5" aria-hidden />+{amount} ml
            </button>
          ))}
        </div>
      </div>
    </Card>
  );
}
