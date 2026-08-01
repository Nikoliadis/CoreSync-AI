"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import { useDebouncedValue } from "@/lib/utils/use-debounced-value";

type Exercise = {
  id: string;
  name: string;
  primaryMuscleGroup?: string | null;
};

export function ExercisePicker({
  open,
  onOpenChange,
  onPick,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (exerciseId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 250);

  const exercises = useQuery({
    queryKey: ["exercises", "picker", debounced],
    queryFn: () =>
      api
        .get<{ items: Exercise[] }>("/v1/exercises", {
          query: { q: debounced || undefined, limit: 25 },
        })
        .then((r) => r.items ?? []),
    enabled: open,
    placeholderData: keepPreviousData,
    // Reference data barely changes; refetching it mid-workout is wasted bandwidth
    // on exactly the connection that can least afford it.
    staleTime: 10 * 60_000,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent variant="sheet" className="max-h-[85vh]">
        <DialogHeader>
          <DialogTitle>Add an exercise</DialogTitle>
          <DialogDescription>Search the catalogue by name.</DialogDescription>
        </DialogHeader>

        <Input
          label="Search"
          placeholder="Bench press, squat, row…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          leadingIcon={<Search className="h-4 w-4" />}
          type="search"
          autoFocus
        />

        <div className="mt-3 max-h-[50vh] overflow-y-auto scrollbar-thin">
          {exercises.isLoading && (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          )}

          {exercises.isSuccess && exercises.data.length === 0 && (
            <p className="py-6 text-center text-body text-text-muted">
              Nothing matched “{debounced}”.
            </p>
          )}

          <ul className="flex flex-col">
            {(exercises.data ?? []).map((exercise) => (
              <li key={exercise.id}>
                <button
                  type="button"
                  onClick={() => {
                    onPick(exercise.id);
                    onOpenChange(false);
                  }}
                  className="flex min-h-12 w-full items-center justify-between gap-3 rounded-md px-3 text-left hover:bg-surface-well"
                >
                  <span className="text-body text-text">{exercise.name}</span>
                  {exercise.primaryMuscleGroup && (
                    <span className="shrink-0 text-overline uppercase text-text-muted">
                      {exercise.primaryMuscleGroup}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </DialogContent>
    </Dialog>
  );
}
