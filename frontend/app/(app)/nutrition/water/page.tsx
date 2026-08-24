"use client";

import { useQuery } from "@tanstack/react-query";
import { Droplets } from "lucide-react";
import { useState } from "react";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { nutritionApi, nutritionKeys } from "@/features/nutrition/api";
import { WaterCard } from "@/features/nutrition/components/water-card";
import { localToday } from "@/features/nutrition/format";

export default function WaterPage() {
  // Fixed to today. Back-filling hydration is not a thing anyone does honestly, and the
  // diary already carries water for any past day worth looking at.
  const [day] = useState(localToday);

  const water = useQuery({
    queryKey: nutritionKeys.water(day),
    queryFn: () => nutritionApi.water(day),
  });

  return (
    <>
      <TopBar title="Water" />

      <PageShell className="max-w-xl">
        {water.isLoading && <Skeleton className="h-32 w-full" />}

        {water.isError && (
          <EmptyState
            icon={<Droplets className="h-8 w-8" />}
            title="Couldn't load your hydration"
            action={<Button onClick={() => water.refetch()}>Try again</Button>}
          />
        )}

        {water.data && (
          <WaterCard totalMl={water.data.totalMl} localDate={water.data.localDate} />
        )}
      </PageShell>
    </>
  );
}
