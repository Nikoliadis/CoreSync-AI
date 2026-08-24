"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Search, UtensilsCrossed } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  MEAL_LABELS,
  type Food,
  type MealType,
  nutritionApi,
  nutritionKeys,
} from "@/features/nutrition/api";
import { kcal, portion } from "@/features/nutrition/format";
import { useDebouncedValue } from "@/lib/utils/use-debounced-value";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mealType: MealType;
  localDate: string;
};

/**
 * Search, pick a portion, log.
 *
 * Two screens rather than one: choosing *what* and choosing *how much* are different
 * decisions, and putting a quantity field on every row of a search result makes the
 * list unreadable on a phone.
 */
export function FoodSearchDialog({ open, onOpenChange, mealType, localDate }: Props) {
  const queryClient = useQueryClient();
  const [term, setTerm] = useState("");
  const [selected, setSelected] = useState<Food | null>(null);

  // 250ms: long enough that a typed word is one request rather than six, short enough
  // that the list feels like it is keeping up.
  const debounced = useDebouncedValue(term, 250);

  // No reset-on-close effect: the diary mounts this only while a meal is being added,
  // so closing unmounts it and the search term and selection go with it. Resetting in an
  // effect would be a cascading render doing the same job worse.

  const results = useQuery({
    queryKey: nutritionKeys.search(debounced),
    queryFn: () => nutritionApi.search(debounced),
    enabled: open && debounced.trim().length > 0,
  });

  // The empty state is a real feature, not a placeholder: most logging is re-logging.
  const recent = useQuery({
    queryKey: nutritionKeys.recent(),
    queryFn: nutritionApi.recent,
    enabled: open && debounced.trim().length === 0,
  });

  const showing = debounced.trim().length > 0 ? results : recent;
  const items = showing.data?.items ?? [];

  if (selected) {
    return (
      <PortionDialog
        food={selected}
        mealType={mealType}
        localDate={localDate}
        onBack={() => setSelected(null)}
        onLogged={() => {
          void queryClient.invalidateQueries({ queryKey: nutritionKeys.all });
          onOpenChange(false);
        }}
      />
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add to {MEAL_LABELS[mealType].toLowerCase()}</DialogTitle>
        </DialogHeader>

        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
            aria-hidden
          />
          <Input
            autoFocus
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="Search foods"
            aria-label="Search foods"
            className="pl-9"
          />
        </div>

        <div className="mt-3 max-h-[50vh] overflow-y-auto">
          {debounced.trim().length === 0 && !recent.isLoading && items.length > 0 && (
            <p className="mb-2 text-overline uppercase text-text-muted">Recent</p>
          )}

          {showing.isLoading && (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          )}

          {showing.isSuccess && items.length === 0 && (
            <EmptyState
              icon={<UtensilsCrossed className="h-8 w-8" />}
              title={
                debounced.trim().length > 0 ? "Nothing matched" : "Nothing logged yet"
              }
              description={
                debounced.trim().length > 0
                  ? "Try a shorter word, or add it as your own food."
                  : "Foods you log will show up here for next time."
              }
            />
          )}

          <ul className="flex flex-col gap-1">
            {items.map((food) => (
              <li key={food.id}>
                <button
                  type="button"
                  onClick={() => setSelected(food)}
                  className="flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left transition-colors hover:bg-surface-well focus-visible:bg-surface-well"
                >
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5">
                      <span className="truncate text-body text-text">{food.name}</span>
                      {food.isVerified && (
                        <BadgeCheck
                          className="h-3.5 w-3.5 shrink-0 text-accent"
                          aria-label="Verified"
                        />
                      )}
                    </span>
                    <span className="mt-0.5 block text-caption text-text-muted">
                      <span className="tabular">{kcal(food.caloriesPer100g)}</span> kcal
                      {food.isLiquid ? " per 100 ml" : " per 100 g"}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Second step: how much of it. */
function PortionDialog({
  food,
  mealType,
  localDate,
  onBack,
  onLogged,
}: {
  food: Food;
  mealType: MealType;
  localDate: string;
  onBack: () => void;
  onLogged: () => void;
}) {
  const defaultServing = useMemo(
    () => food.servings.find((s) => s.isDefault) ?? food.servings[0] ?? null,
    [food.servings],
  );
  const [servingId, setServingId] = useState<string | null>(defaultServing?.id ?? null);
  const [quantity, setQuantity] = useState(defaultServing ? "1" : "100");

  const serving = food.servings.find((s) => s.id === servingId) ?? null;
  const amount = Number(quantity) || 0;
  const totalGrams = serving ? amount * Number(serving.grams) : amount;
  const preview = Math.round((totalGrams / 100) * Number(food.caloriesPer100g));

  const log = useMutation({
    mutationFn: () =>
      nutritionApi.logFood({
        foodId: food.id,
        mealType,
        quantity: amount,
        servingId,
        localDate,
      }),
    onSuccess: () => {
      toast.success(`${food.name} logged`);
      onLogged();
    },
    onError: () => toast.error("Couldn't log that"),
  });

  const unit = food.isLiquid ? "ml" : "g";

  return (
    <Dialog open onOpenChange={(next) => !next && onBack()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{food.name}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-caption text-text-muted">Amount</span>
            <Input
              autoFocus
              inputMode="decimal"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              aria-label="Amount"
            />
          </label>

          {food.servings.length > 0 && (
            <fieldset className="flex flex-col gap-1">
              <legend className="text-caption text-text-muted">Measured in</legend>
              <div className="flex flex-wrap gap-1.5">
                {food.servings.map((option) => (
                  <PortionChip
                    key={option.id}
                    active={servingId === option.id}
                    onClick={() => {
                      setServingId(option.id);
                      setQuantity("1");
                    }}
                  >
                    {option.label}{" "}
                    <span className="text-text-muted">
                      ({portion(option.grams)}
                      {unit})
                    </span>
                  </PortionChip>
                ))}
                <PortionChip
                  active={servingId === null}
                  onClick={() => {
                    setServingId(null);
                    setQuantity("100");
                  }}
                >
                  {unit}
                </PortionChip>
              </div>
            </fieldset>
          )}

          <p className="text-body text-text-secondary">
            <span className="tabular text-h2 text-text">{preview}</span> kcal
            <span className="text-text-muted">
              {" · "}
              <span className="tabular">{portion(String(totalGrams))}</span>
              {unit}
            </span>
          </p>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onBack}>
            Back
          </Button>
          <Button onClick={() => log.mutate()} disabled={amount <= 0 || log.isPending}>
            {log.isPending ? "Adding…" : "Add"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PortionChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        active
          ? "rounded-full border border-accent bg-accent/10 px-3 py-1.5 text-caption text-text"
          : "rounded-full border border-border px-3 py-1.5 text-caption text-text-secondary transition-colors hover:bg-surface-well"
      }
    >
      {children}
    </button>
  );
}
