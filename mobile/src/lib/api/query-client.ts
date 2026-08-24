import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./client";

/**
 * Server state.
 *
 * The retry policy is the interesting part. On a phone in a gym, "failed" usually means
 * "no signal for ten seconds", so a couple of retries genuinely recover. But a 4xx is
 * the server declining, and repeating it is noise — so those are never retried.
 *
 * Mutations are not retried at all: the write path goes through the offline queue,
 * which *is* the retry, and doing both would send everything twice.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
            return false;
          }
          return failureCount < 2;
        },
        staleTime: 30_000,
        // The screen is often reopened seconds later between sets. Refetching every
        // time would be constant traffic for data that has not changed.
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}
