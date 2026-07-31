"use client";

import { useQuery } from "@tanstack/react-query";
import { Dumbbell, Plus } from "lucide-react";
import Link from "next/link";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";

type SessionSummary = {
  id: string;
  name: string;
  localDate: string;
  totalVolumeKg: string;
  totalSets: number;
  durationSeconds: number;
  prCount: number;
};

export default function WorkoutHistoryPage() {
  const history = useQuery({
    queryKey: ["workouts", "history"],
    queryFn: () =>
      api
        .get<{ items: SessionSummary[] }>("/v1/workouts/sessions", { query: { limit: 30 } })
        .then((r) => r.items ?? []),
  });

  return (
    <>
      <TopBar
        title="History"
        action={
          <Button size="sm" asChild>
            <Link href="/workouts/active">
              <Plus className="h-4 w-4" aria-hidden />
              New
            </Link>
          </Button>
        }
      />

      <PageShell>
        {history.isLoading && (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        )}

        {history.isError && (
          <EmptyState
            icon={<Dumbbell className="h-8 w-8" />}
            title="Couldn't load your history"
            description="We'll retry when you're back online, or try again now."
            action={<Button onClick={() => history.refetch()}>Try again</Button>}
          />
        )}

        {history.isSuccess && history.data.length === 0 && (
          <EmptyState
            icon={<Dumbbell className="h-8 w-8" />}
            title="No sessions yet"
            description="Your logged workouts will show up here, most recent first."
            action={
              <Button asChild>
                <Link href="/workouts/active">Start your first workout</Link>
              </Button>
            }
          />
        )}

        {history.isSuccess && history.data.length > 0 && (
          <ul className="flex flex-col gap-3">
            {history.data.map((session) => (
              <li key={session.id}>
                <Link href={`/workouts/${session.id}`}>
                  <Card variant="interactive">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="truncate text-h3 text-text">{session.name}</p>
                        <p className="mt-0.5 text-caption text-text-muted">{session.localDate}</p>
                      </div>
                      <div className="flex shrink-0 gap-4 text-right">
                        <div>
                          <p className="text-overline uppercase text-text-muted">Volume</p>
                          <p className="tabular text-body text-text">{session.totalVolumeKg} kg</p>
                        </div>
                        <div>
                          <p className="text-overline uppercase text-text-muted">Sets</p>
                          <p className="tabular text-body text-text">{session.totalSets}</p>
                        </div>
                      </div>
                    </div>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </PageShell>
    </>
  );
}
