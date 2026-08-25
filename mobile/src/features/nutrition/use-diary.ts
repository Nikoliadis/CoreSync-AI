import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { ApiError } from "@/lib/api/client";

import {
  type Diary,
  type MealType,
  nutritionApi,
  nutritionKeys,
} from "./api";
import { cacheDiary, cachedDiary } from "./cache";

/**
 * A day's diary, with its mutations.
 *
 * Reads fall back to the cache when the network is unreachable, flagged so the UI can
 * say so. Writes do not: `POST /v1/nutrition/diary` has no client id and there is no
 * nutrition sync endpoint, so a queued write replayed later would create a duplicate
 * entry rather than reconcile with the first. Refusing to log offline is honest;
 * silently duplicating somebody's dinner is not.
 *
 * Every mutation invalidates the whole nutrition tree rather than patching the cache by
 * hand. Totals, per-meal totals, remaining-against-target, streak and history all move
 * when one entry changes, and reproducing that arithmetic client-side would be a second
 * implementation of `summarise_day` that drifts from the real one.
 */
export type DiaryView = {
  diary: Diary | undefined;
  isLoading: boolean;
  isError: boolean;
  /** True when the day came from SQLite because the network was unreachable. */
  servedFromCache: boolean;
  refetch: () => void;

  logFood: (input: {
    foodId: string;
    mealType: MealType;
    quantity: number;
    servingId?: string | null;
  }) => Promise<void>;
  quickAdd: (input: {
    mealType: MealType;
    calories: number;
    proteinG?: number;
    carbsG?: number;
    fatG?: number;
    label?: string;
  }) => Promise<void>;
  editEntry: (
    entryId: string,
    changes: { quantity?: number; mealType?: MealType },
  ) => Promise<void>;
  deleteEntry: (entryId: string) => Promise<void>;
  copyFrom: (sourceDate: string, mealType?: MealType) => Promise<number>;
  logWater: (millilitres: number) => Promise<void>;

  isMutating: boolean;
  /** Set when the last mutation failed because there was no connection. */
  mutationOffline: boolean;
};

type CachedDiary = Diary & { fromCache?: boolean };

export function useDiary(localDate: string): DiaryView {
  const queryClient = useQueryClient();

  const query = useQuery<CachedDiary>({
    queryKey: nutritionKeys.diary(localDate),
    queryFn: async () => {
      try {
        const diary = await nutritionApi.diary(localDate);
        // Written on the way through, so the cache holds the days actually looked at.
        void cacheDiary(diary);
        return diary;
      } catch (error) {
        if (error instanceof ApiError && error.isOffline) {
          const cached = await cachedDiary(localDate);
          if (cached) return { ...cached, fromCache: true };
        }
        throw error;
      }
    },
  });

  const invalidate = useCallback(() => {
    // The whole tree: one entry moves totals, per-meal totals, remaining, the streak and
    // the history chart. Patching each by hand would be `summarise_day` reimplemented.
    void queryClient.invalidateQueries({ queryKey: nutritionKeys.all });
  }, [queryClient]);

  const log = useMutation({
    mutationFn: (input: Parameters<DiaryView["logFood"]>[0]) =>
      nutritionApi.logFood({ ...input, localDate }),
    onSuccess: invalidate,
  });

  const quick = useMutation({
    mutationFn: (input: Parameters<DiaryView["quickAdd"]>[0]) =>
      nutritionApi.quickAdd({ ...input, localDate }),
    onSuccess: invalidate,
  });

  const edit = useMutation({
    mutationFn: ({
      entryId,
      changes,
    }: {
      entryId: string;
      changes: { quantity?: number; mealType?: MealType };
    }) => nutritionApi.editEntry(entryId, changes),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (entryId: string) => nutritionApi.deleteEntry(entryId),
    onSuccess: invalidate,
  });

  const copy = useMutation({
    mutationFn: ({ sourceDate, mealType }: { sourceDate: string; mealType?: MealType }) =>
      nutritionApi.copyDay({ sourceDate, targetDate: localDate, mealType }),
    onSuccess: invalidate,
  });

  const water = useMutation({
    mutationFn: (millilitres: number) => nutritionApi.logWater(millilitres, localDate),
    onSuccess: invalidate,
  });

  const mutations = [log, quick, edit, remove, copy, water];
  const lastError = mutations.map((m) => m.error).find(Boolean);

  return {
    diary: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    servedFromCache: Boolean(query.data?.fromCache),
    refetch: () => void query.refetch(),

    logFood: async (input) => {
      await log.mutateAsync(input);
    },
    quickAdd: async (input) => {
      await quick.mutateAsync(input);
    },
    editEntry: async (entryId, changes) => {
      await edit.mutateAsync({ entryId, changes });
    },
    deleteEntry: async (entryId) => {
      await remove.mutateAsync(entryId);
    },
    copyFrom: async (sourceDate, mealType) => {
      const result = await copy.mutateAsync({ sourceDate, mealType });
      return result.copied;
    },
    logWater: async (millilitres) => {
      await water.mutateAsync(millilitres);
    },

    isMutating: mutations.some((m) => m.isPending),
    mutationOffline: lastError instanceof ApiError && lastError.isOffline,
  };
}
