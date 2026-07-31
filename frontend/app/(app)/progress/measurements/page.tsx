"use client";

import { useQuery } from "@tanstack/react-query";
import { Ruler } from "lucide-react";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";

type Measurement = {
  id: string;
  localDate: string;
  sites: Record<string, string>;
  note: string | null;
};

export default function MeasurementsPage() {
  const latest = useQuery({
    queryKey: ["progress", "measurements"],
    queryFn: () =>
      api.get<{ items: Measurement[] }>("/v1/progress/measurements").then((r) => r.items ?? []),
  });

  return (
    <>
      <TopBar title="Measurements" />
      <PageShell className="max-w-3xl">
        <Card>
          <CardHeader>
            <CardTitle>Body measurements</CardTitle>
          </CardHeader>

          {latest.isLoading && <Skeleton className="h-40 w-full" />}

          {latest.isError && (
            <EmptyState
              icon={<Ruler className="h-8 w-8" />}
              title="Couldn't load your measurements"
              action={<Button onClick={() => latest.refetch()}>Try again</Button>}
            />
          )}

          {latest.isSuccess && latest.data.length === 0 && (
            <EmptyState
              icon={<Ruler className="h-8 w-8" />}
              title="Nothing recorded yet"
              description="Waist, chest, arms and the rest — measured every few weeks, they show what the scale alone cannot."
            />
          )}

          {latest.isSuccess && latest.data.length > 0 && (
            <ul className="flex flex-col gap-3">
              {latest.data.map((entry) => (
                <li key={entry.id} className="rounded-md border border-border p-3">
                  <p className="text-caption text-text-muted">{entry.localDate}</p>
                  <dl className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {Object.entries(entry.sites).map(([site, value]) => (
                      <div key={site}>
                        <dt className="text-overline uppercase text-text-muted">
                          {site.replace(/_/g, " ")}
                        </dt>
                        <dd className="tabular text-body text-text">{value} cm</dd>
                      </div>
                    ))}
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </PageShell>
    </>
  );
}
