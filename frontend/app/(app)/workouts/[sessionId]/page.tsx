"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Dumbbell, Trophy } from "lucide-react";
import Link from "next/link";
import { use } from "react";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { StatTile } from "@/components/ui/stat-tile";
import { workoutKeys, workoutsApi } from "@/features/workouts/api";

/**
 * One finished session, read-only.
 *
 * `params` is a promise in Next 16 — synchronous access to request data was removed,
 * and `use()` is how a client component unwraps it.
 */
export default function SessionDetailPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);

  const session = useQuery({
    queryKey: workoutKeys.session(sessionId),
    queryFn: () => workoutsApi.session(sessionId),
  });

  const data = session.data;

  return (
    <>
      <TopBar
        title={data?.name ?? "Workout"}
        action={
          <Button variant="ghost" size="sm" asChild>
            <Link href="/workouts">
              <ArrowLeft className="h-4 w-4" aria-hidden />
              History
            </Link>
          </Button>
        }
      />

      <PageShell className="max-w-4xl">
        {session.isLoading && (
          <div className="flex flex-col gap-4">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        )}

        {session.isError && (
          <EmptyState
            icon={<Dumbbell className="h-8 w-8" />}
            title="Couldn't load that workout"
            description="It may have been deleted, or the connection dropped."
            action={
              <Button asChild>
                <Link href="/workouts">Back to history</Link>
              </Button>
            }
          />
        )}

        {data && (
          <>
            <p className="mb-4 text-caption text-text-muted">{data.localDate}</p>

            <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatTile
                label="Volume"
                value={Math.round(Number(data.totalVolumeKg)).toLocaleString()}
                unit="kg"
              />
              <StatTile label="Sets" value={data.totalSets} />
              <StatTile label="Exercises" value={data.exercises.length} />
              <StatTile
                label="Duration"
                value={Math.round((data.durationSeconds ?? 0) / 60)}
                unit="min"
              />
            </div>

            <div className="flex flex-col gap-4">
              {data.exercises.map((exercise) => (
                <Card key={exercise.id}>
                  <CardHeader>
                    <CardTitle>{exercise.exerciseName}</CardTitle>
                  </CardHeader>

                  {exercise.notes && (
                    <p className="mb-3 text-caption text-text-secondary">{exercise.notes}</p>
                  )}

                  <table className="w-full">
                    <thead>
                      <tr>
                        <th className="pb-1 text-left text-overline uppercase text-text-muted">
                          Set
                        </th>
                        <th className="pb-1 text-right text-overline uppercase text-text-muted">
                          kg
                        </th>
                        <th className="pb-1 text-right text-overline uppercase text-text-muted">
                          Reps
                        </th>
                        <th className="pb-1 text-right text-overline uppercase text-text-muted">
                          e1RM
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {exercise.sets.map((set) => (
                        <tr key={set.id} className="border-t border-border">
                          <td className="py-2 text-caption text-text-muted">
                            {set.setType === "normal" ? (
                              set.setNumber
                            ) : (
                              <span className="rounded-sm bg-surface-well px-1.5 py-0.5 uppercase">
                                {set.setType}
                              </span>
                            )}
                          </td>
                          <td className="tabular py-2 text-right text-numeric-table text-text">
                            {set.weightKg ?? "—"}
                          </td>
                          <td className="tabular py-2 text-right text-numeric-table text-text">
                            {set.reps ?? "—"}
                          </td>
                          <td className="tabular py-2 text-right text-numeric-table text-text-secondary">
                            {set.estimatedOneRepMax ? (
                              <span className="inline-flex items-center gap-1">
                                <Trophy className="h-3 w-3 text-accent-text" aria-hidden />
                                {set.estimatedOneRepMax}
                              </span>
                            ) : (
                              "—"
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              ))}
            </div>
          </>
        )}
      </PageShell>
    </>
  );
}
