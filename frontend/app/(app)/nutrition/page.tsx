"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Plus, Trash2, UtensilsCrossed } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ProgressRing } from "@/components/ui/progress-ring";
import { Skeleton } from "@/components/ui/skeleton";
import {
  MEAL_LABELS,
  MEAL_ORDER,
  type DiaryEntry,
  type MealType,
  nutritionApi,
  nutritionKeys,
} from "@/features/nutrition/api";
import { FoodSearchDialog } from "@/features/nutrition/components/food-search-dialog";
import { WaterCard } from "@/features/nutrition/components/water-card";
import { friendlyDate, kcal, localToday, macroSlots, portion, shiftDate } from "@/features/nutrition/format";

export default function NutritionPage() {
  const queryClient = useQueryClient();
  const [day, setDay] = useState(localToday);
  const [adding, setAdding] = useState<MealType | null>(null);

  const diary = useQuery({
    queryKey: nutritionKeys.diary(day),
    queryFn: () => nutritionApi.diary(day),
  });

  const remove = useMutation({
    mutationFn: nutritionApi.deleteEntry,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: nutritionKeys.all });
      toast.success("Removed");
    },
    onError: () => toast.error("Couldn't remove that"),
  });

  const data = diary.data;
  const target = data?.targets ? kcal(data.targets.calories) : null;
  const eaten = kcal(data?.totals.calories);
  const byMeal = new Map<MealType, DiaryEntry[]>();
  for (const meal of MEAL_ORDER) byMeal.set(meal, []);
  for (const entry of data?.entries ?? []) byMeal.get(entry.mealType)?.push(entry);

  return (
    <>
      <TopBar title="Nutrition" />

      <PageShell className="max-w-3xl">
        <DayStepper day={day} onChange={setDay} />

        {diary.isLoading && (
          <div className="mt-4 flex flex-col gap-3">
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        )}

        {diary.isError && (
          <EmptyState
            icon={<UtensilsCrossed className="h-8 w-8" />}
            title="Couldn't load your diary"
            action={<Button onClick={() => diary.refetch()}>Try again</Button>}
          />
        )}

        {data && (
          <div className="mt-4 flex flex-col gap-3">
            <Card className="flex flex-col items-center gap-4 sm:flex-row sm:gap-6">
              {target ? (
                <ProgressRing value={eaten} max={target} label="Eaten" unit="kcal" />
              ) : (
                <div className="flex flex-col items-center px-4">
                  <span className="tabular text-display text-text">{eaten}</span>
                  <span className="text-caption text-text-muted">kcal</span>
                </div>
              )}

              <div className="min-w-0 flex-1">
                {target ? (
                  <p className="text-body text-text-secondary">
                    <span className="tabular text-h2 text-text">
                      {Math.max(target - eaten, 0)}
                    </span>{" "}
                    kcal left of <span className="tabular">{target}</span>
                  </p>
                ) : (
                  /* No target is not a failure state. Nothing to be "over" or "under". */
                  <p className="text-body text-text-secondary">
                    Set a calorie target to see how the day is tracking.
                  </p>
                )}

                <div className="mt-3 flex flex-col gap-2">
                  {macroSlots(data.totals).map((slot) => {
                    const goal =
                      data.targets && slot.key === "protein"
                        ? Number(data.targets.proteinG)
                        : data.targets && slot.key === "carbs"
                          ? Number(data.targets.carbsG)
                          : data.targets
                            ? Number(data.targets.fatG)
                            : null;
                    return (
                      <MacroBar
                        key={slot.key}
                        label={slot.label}
                        grams={slot.grams}
                        goal={goal}
                        color={slot.color}
                      />
                    );
                  })}
                </div>
              </div>
            </Card>

            <WaterCard totalMl={data.waterMl} localDate={day} />

            {MEAL_ORDER.map((meal) => {
              const entries = byMeal.get(meal) ?? [];
              const totals = data.byMeal.find((m) => m.mealType === meal);
              return (
                <Card key={meal}>
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <h2 className="text-h3 text-text">{MEAL_LABELS[meal]}</h2>
                    <div className="flex items-center gap-2">
                      <span className="tabular text-caption text-text-muted">
                        {kcal(totals?.macros.calories)} kcal
                      </span>
                      <Button size="sm" variant="ghost" onClick={() => setAdding(meal)}>
                        <Plus className="h-4 w-4" aria-hidden />
                        <span className="sr-only">Add to {MEAL_LABELS[meal]}</span>
                      </Button>
                    </div>
                  </div>

                  {entries.length === 0 ? (
                    <p className="py-2 text-caption text-text-muted">Nothing logged.</p>
                  ) : (
                    <ul className="flex flex-col">
                      {entries.map((entry) => (
                        <li
                          key={entry.id}
                          className="flex items-center justify-between gap-3 border-t border-border py-2 first:border-t-0"
                        >
                          <div className="min-w-0">
                            <p className="truncate text-body text-text">
                              {entry.displayName}
                            </p>
                            <p className="mt-0.5 text-caption text-text-muted">
                              <span className="tabular">
                                {portion(entry.totalGrams)}
                              </span>
                              g · P{" "}
                              <span className="tabular">
                                {Math.round(Number(entry.macros.proteinG))}
                              </span>{" "}
                              C{" "}
                              <span className="tabular">
                                {Math.round(Number(entry.macros.carbsG))}
                              </span>{" "}
                              F{" "}
                              <span className="tabular">
                                {Math.round(Number(entry.macros.fatG))}
                              </span>
                            </p>
                          </div>
                          <div className="flex shrink-0 items-center gap-1">
                            <span className="tabular text-body text-text">
                              {kcal(entry.macros.calories)}
                            </span>
                            <button
                              type="button"
                              onClick={() => remove.mutate(entry.id)}
                              className="flex h-11 w-11 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-well hover:text-critical"
                              aria-label={`Remove ${entry.displayName}`}
                            >
                              <Trash2 className="h-4 w-4" aria-hidden />
                            </button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              );
            })}
          </div>
        )}
      </PageShell>

      {adding && (
        <FoodSearchDialog
          open
          onOpenChange={(next) => !next && setAdding(null)}
          mealType={adding}
          localDate={day}
        />
      )}
    </>
  );
}

function DayStepper({ day, onChange }: { day: string; onChange: (next: string) => void }) {
  const today = localToday();
  return (
    <div className="flex items-center justify-between gap-2">
      <button
        type="button"
        onClick={() => onChange(shiftDate(day, -1))}
        className="flex h-11 w-11 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-well"
        aria-label="Previous day"
      >
        <ChevronLeft className="h-5 w-5" aria-hidden />
      </button>
      <p className="text-h3 text-text">{friendlyDate(day)}</p>
      <button
        type="button"
        // Logging ahead is meaningless, and an endlessly forward-scrolling diary is a
        // way to get lost in empty days.
        disabled={day >= today}
        onClick={() => onChange(shiftDate(day, 1))}
        className="flex h-11 w-11 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-well disabled:opacity-30"
        aria-label="Next day"
      >
        <ChevronRight className="h-5 w-5" aria-hidden />
      </button>
    </div>
  );
}

function MacroBar({
  label,
  grams,
  goal,
  color,
}: {
  label: string;
  grams: number;
  goal: number | null;
  color: string;
}) {
  const pct = goal && goal > 0 ? Math.min((grams / goal) * 100, 100) : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between text-caption">
        <span className="text-text-secondary">{label}</span>
        <span className="tabular text-text-muted">
          {grams}
          {goal ? ` / ${Math.round(goal)}` : ""} g
        </span>
      </div>
      <div
        className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-well"
        role="progressbar"
        aria-label={label}
        aria-valuenow={grams}
        aria-valuemin={0}
        aria-valuemax={goal ?? undefined}
      >
        <div
          className="h-full rounded-full transition-[width]"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}
