"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Trophy } from "lucide-react";
import { toast } from "sonner";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  achievementKeys,
  achievementsApi,
  progressLabel,
  type Achievement,
} from "@/features/achievements/api";
import { cn } from "@/lib/utils/cn";

/**
 * Tiers change the badge, never the difficulty — they are presentation only.
 * Bronze and gold both use accent-derived tones so the one-accent rule holds.
 */
const TIER_RING: Record<Achievement["tier"], string> = {
  bronze: "text-serious",
  silver: "text-text-secondary",
  gold: "text-accent-text",
};

export default function AchievementsPage() {
  const queryClient = useQueryClient();

  const list = useQuery({ queryKey: achievementKeys.list, queryFn: achievementsApi.list });

  const evaluate = useMutation({
    mutationFn: achievementsApi.evaluate,
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: achievementKeys.list });
      if (result.newlyEarned.length === 0) {
        toast("Nothing new yet", { description: "Keep going — progress is shown below." });
      } else {
        for (const earned of result.newlyEarned) {
          toast.success(earned.name, { description: earned.description });
        }
      }
    },
    onError: () => toast.error("Couldn't check for achievements"),
  });

  const achievements = list.data?.achievements ?? [];

  return (
    <>
      <TopBar
        title="Achievements"
        action={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => evaluate.mutate()}
            loading={evaluate.isPending}
          >
            Check now
          </Button>
        }
      />

      <PageShell className="max-w-4xl">
        {list.isLoading && (
          <div className="grid gap-3 sm:grid-cols-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        )}

        {list.isError && (
          <EmptyState
            icon={<Trophy className="h-8 w-8" />}
            title="Couldn't load your achievements"
            action={<Button onClick={() => list.refetch()}>Try again</Button>}
          />
        )}

        {list.data && (
          <>
            <p className="mb-5 text-body text-text-secondary">
              <span className="tabular text-text">{list.data.earnedCount}</span> of{" "}
              <span className="tabular">{list.data.totalCount}</span> earned.
            </p>

            <ul className="grid gap-3 sm:grid-cols-2">
              {achievements.map((achievement) => {
                const progress = Math.min(Number(achievement.progress) || 0, 1);
                return (
                  <li key={achievement.code}>
                    <Card
                      className={cn(
                        "flex h-full items-start gap-3",
                        !achievement.earned && "opacity-75",
                      )}
                    >
                      <span
                        className={cn(
                          "flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-well",
                          achievement.earned ? TIER_RING[achievement.tier] : "text-text-muted",
                        )}
                        aria-hidden
                      >
                        {achievement.earned ? (
                          <Trophy className="h-5 w-5" />
                        ) : (
                          <Lock className="h-4 w-4" />
                        )}
                      </span>

                      <div className="min-w-0 flex-1">
                        <p className="text-body text-text">{achievement.name}</p>
                        <p className="mt-0.5 text-caption text-text-secondary">
                          {achievement.description}
                        </p>

                        {achievement.earned ? (
                          <p className="mt-2 text-overline uppercase text-text-muted">
                            {achievement.earnedAt
                              ? `Earned ${achievement.earnedAt.slice(0, 10)}`
                              : "Earned"}
                          </p>
                        ) : (
                          <div className="mt-2">
                            {/* A locked icon alone says nothing about how close you are,
                                so unearned entries carry their progress. */}
                            <div
                              className="h-1 w-full overflow-hidden rounded-full bg-surface-well"
                              role="progressbar"
                              aria-valuenow={Math.round(progress * 100)}
                              aria-valuemin={0}
                              aria-valuemax={100}
                              aria-label={`${achievement.name} progress`}
                            >
                              <div
                                className="h-full rounded-full bg-accent transition-[width] duration-[420ms]"
                                style={{ width: `${progress * 100}%` }}
                              />
                            </div>
                            <p className="tabular mt-1 text-overline uppercase text-text-muted">
                              {progressLabel(achievement)}
                            </p>
                          </div>
                        )}
                      </div>
                    </Card>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </PageShell>
    </>
  );
}
