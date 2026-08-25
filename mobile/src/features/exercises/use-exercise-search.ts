import { useInfiniteQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { useDebouncedValue } from "@/lib/utils/use-debounced-value";

import {
  PAGE_SIZE,
  type Exercise,
  type ExerciseFilters,
  type ExercisePage,
  exerciseKeys,
  exercisesApi,
} from "./api";
import { cacheExercises, searchCached } from "./cache";

/**
 * Paged exercise search with an offline fallback.
 *
 * Online, results come from the API and are written to the cache on the way through.
 * Offline, the same query is answered from whatever was cached — with `servedFromCache`
 * set, so the UI can say where the answer came from rather than quietly presenting stale
 * data as live.
 *
 * A cache miss while offline is an empty result and a clear message. It is never an
 * invented exercise: a fabricated id would be accepted locally and then rejected by the
 * server on sync, which loses the set that was logged against it.
 */
export type ExerciseSearch = {
  exercises: Exercise[];
  total: number;
  isLoading: boolean;
  isError: boolean;
  isFetchingMore: boolean;
  hasMore: boolean;
  /** True when the results came from SQLite because the network was unreachable. */
  servedFromCache: boolean;
  query: string;
  setQuery: (value: string) => void;
  filters: ExerciseFilters;
  setFilter: <K extends keyof ExerciseFilters>(key: K, value: ExerciseFilters[K]) => void;
  clearFilters: () => void;
  loadMore: () => void;
  retry: () => void;
};

type Page = ExercisePage & { fromCache: boolean };

export function useExerciseSearch(): ExerciseSearch {
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<ExerciseFilters>({});

  // 250ms: long enough that a typed word is one request rather than six, short enough
  // that the list feels like it is keeping up.
  const debouncedQuery = useDebouncedValue(query, 250);
  const active: ExerciseFilters = { ...filters, q: debouncedQuery.trim() || undefined };

  const search = useInfiniteQuery<Page>({
    queryKey: exerciseKeys.list(active),
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const offset = pageParam as number;
      try {
        const page = await exercisesApi.search(active, offset);
        // Written on the way through, so the cache fills with what this user actually
        // looks at rather than a bulk download nobody asked for.
        void cacheExercises(page.items);
        return { ...page, fromCache: false };
      } catch (error) {
        // Only a dead connection falls back. A 4xx is the server declining and the
        // cache would be answering a different question.
        if (error instanceof ApiError && error.isOffline) {
          const items = await searchCached(active, offset + PAGE_SIZE);
          const window = items.slice(offset, offset + PAGE_SIZE);
          return {
            items: window,
            total: items.length,
            limit: PAGE_SIZE,
            offset,
            hasMore: items.length > offset + PAGE_SIZE,
            fromCache: true,
          };
        }
        throw error;
      }
    },
    getNextPageParam: (last) => (last.hasMore ? last.offset + last.limit : undefined),
  });

  const setFilter = useCallback(
    <K extends keyof ExerciseFilters>(key: K, value: ExerciseFilters[K]) => {
      setFilters((current) => {
        // Tapping an active filter clears it. Two taps to undo a one-tap action is the
        // kind of thing that makes a filter row annoying to use.
        if (current[key] === value) {
          const next = { ...current };
          delete next[key];
          return next;
        }
        return { ...current, [key]: value };
      });
    },
    [],
  );

  const clearFilters = useCallback(() => setFilters({}), []);

  const pages = search.data?.pages ?? [];
  const exercises = pages.flatMap((page) => page.items);

  return {
    exercises,
    total: pages[0]?.total ?? 0,
    isLoading: search.isLoading,
    isError: search.isError,
    isFetchingMore: search.isFetchingNextPage,
    hasMore: Boolean(search.hasNextPage),
    servedFromCache: pages.some((page) => page.fromCache),
    query,
    setQuery,
    filters,
    setFilter,
    clearFilters,
    loadMore: () => {
      if (search.hasNextPage && !search.isFetchingNextPage) void search.fetchNextPage();
    },
    retry: () => void search.refetch(),
  };
}
