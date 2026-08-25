import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/lib/api/client";

import {
  type ExerciseHistory,
  type PersonalRecord,
  historyApi,
  historyKeys,
} from "./history-api";

/**
 * Last session and standing records for one exercise.
 *
 * Deliberately soft. The active workout screen is offline-first and nothing on it waits
 * for the network; this is the one thing on the screen that comes from the server, so it
 * has to fail invisibly. No error state, no retry banner, no spinner — an unreachable
 * server means an empty PREV column, which is exactly what a first-ever session shows.
 *
 * `staleTime` is long because the previous session is a fact that does not change while
 * you are training. Refetching between every set would spend battery to re-learn it.
 */
export function useExerciseHistory(exerciseId: string): {
  history: ExerciseHistory | undefined;
  records: PersonalRecord[] | undefined;
} {
  const history = useQuery({
    queryKey: historyKeys.history(exerciseId),
    queryFn: () => historyApi.forExercise(exerciseId),
    staleTime: 30 * 60 * 1000,
    // One retry, and none at all when the device is plainly offline. Retrying into a
    // dead network mid-workout is battery spent on a column that degrades gracefully.
    retry: (count, error) => count < 1 && !(error instanceof ApiError && error.isOffline),
  });

  const records = useQuery({
    queryKey: historyKeys.records(exerciseId),
    queryFn: () => historyApi.records(exerciseId),
    staleTime: 30 * 60 * 1000,
    retry: (count, error) => count < 1 && !(error instanceof ApiError && error.isOffline),
  });

  return { history: history.data, records: records.data };
}
