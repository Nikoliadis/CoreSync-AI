"use client";

import { useQuery } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { axisStyle, gridStyle, SERIES_COLOR, tooltipStyle } from "@/components/charts/chart-theme";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { StatTile } from "@/components/ui/stat-tile";
import { api } from "@/lib/api/client";

type WeightPoint = { localDate: string; weightKg: string; trendKg: string };
type WeightSeries = {
  points: WeightPoint[];
  latestWeightKg: string | null;
  latestTrendKg: string | null;
  changeKg: string | null;
  weeklyRateKg: string | null;
};

export default function ProgressPage() {
  const series = useQuery({
    queryKey: ["progress", "weight"],
    queryFn: () => api.get<WeightSeries>("/v1/progress/weight"),
  });

  const points = (series.data?.points ?? []).map((point) => ({
    date: point.localDate,
    weight: Number(point.weightKg),
    trend: Number(point.trendKg),
  }));

  return (
    <>
      <TopBar title="Progress" />

      <PageShell>
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile
            label="Weight"
            value={series.data?.latestWeightKg ?? "—"}
            unit="kg"
            higherIsBetter={false}
          />
          <StatTile
            label="Trend"
            value={series.data?.latestTrendKg ?? "—"}
            unit="kg"
            higherIsBetter={false}
          />
          <StatTile
            label="Change"
            value={series.data?.changeKg ?? "—"}
            unit="kg"
            higherIsBetter={false}
          />
          <StatTile
            label="Rate"
            value={series.data?.weeklyRateKg ?? "—"}
            unit="kg/wk"
            higherIsBetter={false}
          />
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Weight trend</CardTitle>
          </CardHeader>

          {series.isLoading && <Skeleton className="h-72 w-full" />}

          {series.isError && (
            <EmptyState
              icon={<TrendingUp className="h-8 w-8" />}
              title="Couldn't load your weight history"
              action={<Button onClick={() => series.refetch()}>Try again</Button>}
            />
          )}

          {series.isSuccess && points.length === 0 && (
            <EmptyState
              icon={<TrendingUp className="h-8 w-8" />}
              title="No weigh-ins yet"
              description="Log a few and the smoothed trend line will show what's actually happening, past the day-to-day noise."
            />
          )}

          {series.isSuccess && points.length > 0 && (
            <>
              {/* Direct labels in the legend, because the chart is also read on
                  light surfaces where some slots warn on contrast (docs/09 §3.1). */}
              <div className="mb-3 flex gap-4">
                <span className="flex items-center gap-1.5 text-caption text-text-secondary">
                  <span
                    className="h-0.5 w-4 rounded-full"
                    style={{ background: SERIES_COLOR.weight }}
                    aria-hidden
                  />
                  Trend
                </span>
                <span className="flex items-center gap-1.5 text-caption text-text-muted">
                  <span className="h-0.5 w-4 rounded-full bg-text-muted opacity-50" aria-hidden />
                  Daily weigh-in
                </span>
              </div>

              <div className="h-72 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={points} margin={{ top: 4, right: 8, bottom: 4, left: -16 }}>
                    <CartesianGrid {...gridStyle} />
                    <XAxis dataKey="date" {...axisStyle} minTickGap={32} />
                    <YAxis {...axisStyle} domain={["dataMin - 1", "dataMax + 1"]} width={48} />
                    <Tooltip {...tooltipStyle} />
                    <Line
                      type="monotone"
                      dataKey="weight"
                      stroke="var(--color-text-muted)"
                      strokeWidth={1}
                      strokeOpacity={0.5}
                      dot={false}
                      name="Weigh-in"
                    />
                    <Line
                      type="monotone"
                      dataKey="trend"
                      stroke={SERIES_COLOR.weight}
                      strokeWidth={2.5}
                      dot={false}
                      name="Trend"
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {/* The table fallback required for every chart (docs/09 §9). */}
              <details className="mt-3">
                <summary className="cursor-pointer text-caption text-text-muted hover:text-text">
                  View as table
                </summary>
                <div className="mt-2 max-h-64 overflow-auto">
                  <table className="w-full text-caption">
                    <thead>
                      <tr>
                        <th className="border-b border-border py-1.5 text-left text-overline uppercase text-text-muted">
                          Date
                        </th>
                        <th className="border-b border-border py-1.5 text-right text-overline uppercase text-text-muted">
                          Weight
                        </th>
                        <th className="border-b border-border py-1.5 text-right text-overline uppercase text-text-muted">
                          Trend
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {points.map((point) => (
                        <tr key={point.date}>
                          <td className="border-b border-border py-1.5 text-text-secondary">
                            {point.date}
                          </td>
                          <td className="tabular border-b border-border py-1.5 text-right text-text">
                            {point.weight}
                          </td>
                          <td className="tabular border-b border-border py-1.5 text-right text-text">
                            {point.trend}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </>
          )}
        </Card>
      </PageShell>
    </>
  );
}
