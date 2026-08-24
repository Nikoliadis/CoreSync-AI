"use client";

import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, Search, UtensilsCrossed } from "lucide-react";
import { useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { type Food, nutritionApi, nutritionKeys } from "@/features/nutrition/api";
import { kcal } from "@/features/nutrition/format";
import { useDebouncedValue } from "@/lib/utils/use-debounced-value";

/**
 * Picks one food to use as an ingredient.
 *
 * Deliberately not the diary's search dialog: that one ends in "how much of this did you
 * eat, log it now", and this one ends in "add it to the list I am building". Sharing the
 * component would mean a mode flag threaded through every branch of it.
 */
export function IngredientPicker({
  onPick,
  onCancel,
}: {
  onPick: (food: Food) => void;
  onCancel: () => void;
}) {
  const [term, setTerm] = useState("");
  const debounced = useDebouncedValue(term, 250);

  const results = useQuery({
    queryKey: nutritionKeys.search(debounced),
    queryFn: () => nutritionApi.search(debounced),
    enabled: debounced.trim().length > 0,
  });

  const recent = useQuery({
    queryKey: nutritionKeys.recent(),
    queryFn: nutritionApi.recent,
    enabled: debounced.trim().length === 0,
  });

  const showing = debounced.trim().length > 0 ? results : recent;
  const items = showing.data?.items ?? [];

  return (
    <Dialog open onOpenChange={(next) => !next && onCancel()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add an ingredient</DialogTitle>
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
          {showing.isLoading && (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          )}

          {showing.isSuccess && items.length === 0 && (
            <EmptyState
              icon={<UtensilsCrossed className="h-8 w-8" />}
              title="Nothing matched"
              description="Try a shorter word."
            />
          )}

          <ul className="flex flex-col gap-1">
            {items.map((food) => (
              <li key={food.id}>
                <button
                  type="button"
                  onClick={() => onPick(food)}
                  className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left transition-colors hover:bg-surface-well focus-visible:bg-surface-well"
                >
                  <span className="min-w-0 flex-1">
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
