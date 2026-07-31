import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api/client";

/**
 * Query defaults (docs/07 §3.4).
 *
 * The two decisions that matter:
 *
 * `staleTime: 60s` — this app's data changes when *the user* changes it, and
 * those paths already invalidate explicitly. Without a stale time, every window
 * focus refetches the dashboard, which on mobile means a spinner every time
 * someone returns from the rest timer.
 *
 * Retry excludes 4xx. Retrying a 401 or a 422 cannot succeed; it just delays the
 * error the user needs to see by several seconds.
 */
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        gcTime: 5 * 60_000,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
            return false;
          }
          return failureCount < 2;
        },
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
      },
      mutations: {
        // Mutations are never retried automatically: a logged set that appears
        // twice is worse than one that fails visibly and can be retried by hand.
        retry: false,
      },
    },
  });
}
