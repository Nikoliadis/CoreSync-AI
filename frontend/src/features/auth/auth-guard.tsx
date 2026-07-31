"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuthStore } from "@/features/auth/store";
import { useSessionBootstrap } from "@/features/auth/hooks";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Gate for the authenticated shell.
 *
 * The redirect waits for `initialising` to settle. Redirecting while the refresh
 * is still in flight would bounce every signed-in user to /login on a hard
 * reload — the classic in-memory-token bug.
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  useSessionBootstrap();

  const user = useAuthStore((s) => s.user);
  const initialising = useAuthStore((s) => s.initialising);
  const router = useRouter();

  useEffect(() => {
    if (!initialising && !user) router.replace("/login");
  }, [initialising, user, router]);

  if (initialising) {
    return (
      <div className="flex min-h-dvh flex-col gap-4 p-6" aria-busy="true" aria-live="polite">
        <span className="sr-only">Restoring your session…</span>
        <Skeleton className="h-16 w-full" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  // The effect above is already redirecting; rendering nothing avoids a flash of
  // the shell for an unauthenticated visitor.
  if (!user) return null;

  return <>{children}</>;
}
