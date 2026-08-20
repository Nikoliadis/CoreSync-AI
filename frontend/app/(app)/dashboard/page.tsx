"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Bot, Dumbbell, Flame, Plus, Scale, TrendingUp, Trophy } from "lucide-react";
import Link from "next/link";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { axisStyle, SERIES_COLOR, tooltipStyle } from "@/components/charts/chart-theme";
import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ProgressRing } from "@/components/ui/progress-ring";
import { Skeleton, SkeletonCard } from "@/components/ui/skeleton";
import { StatTile } from "@/components/ui/stat-tile";
import { coachApi } from "@/features/coach/api";
import { dashboardApi, dashboardKeys, percentChange } from "@/features/dashboard/api";
import { useActiveSession } from "@/features/workouts/mutations";

const stagger = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.03 } },
};
const item = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.26, ease: [0.2, 0, 0, 1] as const } },
};

const MACROS = [
  { label: "Calories", unit: "kcal", color: "var(--color-chart-2)" },
  { label: "Protein", unit: "g", color: "var(--color-chart-3)" },
  { label: "Carbs", unit: "g", color: "var(--color-chart-4)" },
  { label: "Fat", unit: "g", color: "var(--color-chart-5)" },
  { label: "Water", unit: "ml", color: "var(--color-chart-1)" },
];

export default function DashboardPage() {
  const dashboard = useQuery({
    queryKey: dashboardKeys.overview,
    queryFn: dashboardApi.overview,
  });

  const active = useActiveSession();

  const insights = useQuery({
    queryKey: ["coach", "insights"],
    queryFn: coachApi.listInsights,
    // The coach is optional infrastructure. A missing provider must not blank the
    // dashboard, so a failure here degrades to an empty card rather than an error.
    retry: false,
  });

  const data = dashboard.data;
  const thisWeek = data?.thisWeek;
  const lastWeek = data?.lastWeek;

  const volumeDelta =
    thisWeek && lastWeek
      ? percentChange(Number(thisWeek.totalVolumeKg), Number(lastWeek.totalVolumeKg))
      : null;
  const sessionDelta =
    thisWeek && lastWeek ? thisWeek.workoutCount - lastWeek.workoutCount : undefined;

  const weightPoints = (data?.weight.points ?? []).map((point) => ({
    date: point.localDate,
    trend: Number(point.trendKg),
  }));

  return (
    <>
      <TopBar
        title="Dashboard"
        action={
          <Button asChild size="sm" className="hidden sm:inline-flex">
            <Link href="/workouts/active">
              <Plus className="h-4 w-4" aria-hidden />
              {active.data ? "Resume workout" : "Start workout"}
            </Link>
          </Button>
        }
      />

      <PageShell>
        <motion.div
          variants={stagger}
          initial="hidden"
          animate="show"
          className="flex flex-col gap-6"
        >
          {/* --- training ---------------------------------------------------- */}
          <motion.section variants={item} aria-labelledby="training-heading">
            <h2 id="training-heading" className="sr-only">
              Training
            </h2>

            {dashboard.isLoading ? (
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <SkeletonCard key={i} />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <StatTile
                  label="Workout streak"
                  value={data?.workoutStreak.current ?? 0}
                  unit={data?.workoutStreak.current === 1 ? "week" : "weeks"}
                />
                <StatTile
                  label="This week"
                  value={thisWeek?.workoutCount ?? 0}
                  unit="sessions"
                  delta={sessionDelta}
                  deltaLabel="vs last week"
                />
                <StatTile
                  label="Volume, 7d"
                  value={Math.round(Number(thisWeek?.totalVolumeKg ?? 0)).toLocaleString()}
                  unit="kg"
                  delta={volumeDelta ?? undefined}
                  deltaLabel="%"
                />
                <StatTile
                  label="Weight"
                  value={data?.weight.latestTrendKg ?? "—"}
                  unit="kg"
                  // Whether a rising number is good depends on the user's goal, so the
                  // tile is told rather than left to guess (docs/09 §3.3).
                  higherIsBetter={false}
                  delta={data?.weight.weeklyRateKg ? Number(data.weight.weeklyRateKg) : undefined}
                  deltaLabel="kg/wk"
                />
              </div>
            )}
          </motion.section>

          {/* --- nutrition (no backend yet) ---------------------------------- */}
          <motion.section variants={item} aria-labelledby="fuel-heading">
            <h2 id="fuel-heading" className="mb-3 text-h2">
              Today&apos;s fuel
            </h2>
            <Card>
              <div className="flex flex-col items-center gap-6 py-4 sm:flex-row sm:justify-around">
                {MACROS.map((macro) => (
                  <div key={macro.label} className="flex flex-col items-center gap-2">
                    <ProgressRing
                      value={0}
                      max={1}
                      label={macro.label}
                      unit={macro.unit}
                      size={92}
                      strokeWidth={8}
                      color={macro.color}
                    />
                    <span className="text-caption text-text-secondary">{macro.label}</span>
                  </div>
                ))}
              </div>
              {/* Stated rather than shown as zeros: "0 kcal" cannot be told apart from
                  "ate nothing", which is why the API returns null here. */}
              <p className="mt-2 rounded-md bg-surface-well p-3 text-center text-caption text-text-muted">
                Nutrition tracking isn&apos;t live yet, so these are empty rather than zero.
              </p>
            </Card>
          </motion.section>

          <div className="grid gap-6 lg:grid-cols-3">
            {/* --- today's workout ------------------------------------------ */}
            <motion.section
              variants={item}
              className="lg:col-span-2"
              aria-labelledby="today-heading"
            >
              <Card className="h-full">
                <CardHeader>
                  <CardTitle id="today-heading">
                    {active.data ? "In progress" : "Today's workout"}
                  </CardTitle>
                </CardHeader>

                {active.isLoading ? (
                  <Skeleton className="h-32 w-full" />
                ) : active.data ? (
                  <div>
                    <p className="text-h3 text-text">{active.data.name}</p>
                    <p className="mt-1 text-caption text-text-muted">
                      <span className="tabular">{active.data.totalSets}</span> sets ·{" "}
                      <span className="tabular">
                        {Math.round(Number(active.data.totalVolumeKg)).toLocaleString()}
                      </span>{" "}
                      kg
                    </p>
                    <Button className="mt-4" asChild>
                      <Link href="/workouts/active">Resume</Link>
                    </Button>
                  </div>
                ) : (
                  <EmptyState
                    icon={<Dumbbell className="h-8 w-8" />}
                    title="Ready when you are"
                    description="Nothing logged today. Start from a routine or log freestyle."
                    action={
                      <Button asChild>
                        <Link href="/workouts/active">Start a workout</Link>
                      </Button>
                    }
                  />
                )}
              </Card>
            </motion.section>

            {/* --- coach ----------------------------------------------------- */}
            <motion.section variants={item} aria-labelledby="coach-heading">
              <Card className="h-full">
                <CardHeader>
                  <CardTitle id="coach-heading">From your coach</CardTitle>
                </CardHeader>

                {insights.data && insights.data.length > 0 ? (
                  <ul className="flex flex-col gap-3">
                    {insights.data.slice(0, 3).map((insight) => (
                      <li key={insight.id} className="rounded-md border border-border p-3">
                        <p className="text-body text-text">{insight.title}</p>
                        <p className="mt-1 text-caption text-text-secondary">{insight.body}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState
                    icon={<Bot className="h-8 w-8" />}
                    title="No insights yet"
                    description="Log a few sessions and the coach starts spotting patterns worth telling you about."
                    action={
                      <Button variant="secondary" asChild>
                        <Link href="/coach">Ask the coach</Link>
                      </Button>
                    }
                  />
                )}
              </Card>
            </motion.section>
          </div>

          {/* --- weight trend ------------------------------------------------ */}
          <motion.section variants={item} aria-labelledby="trend-heading">
            <Card>
              <CardHeader>
                <CardTitle id="trend-heading">Weight trend</CardTitle>
              </CardHeader>

              {dashboard.isLoading && <Skeleton className="h-56 w-full" />}

              {dashboard.isSuccess && weightPoints.length < 2 && (
                <EmptyState
                  icon={<Scale className="h-8 w-8" />}
                  title="Not enough weigh-ins yet"
                  description="Log a couple and the smoothed trend shows what's actually happening, past the daily noise."
                  action={
                    <Button variant="secondary" asChild>
                      <Link href="/progress">Log a weigh-in</Link>
                    </Button>
                  }
                />
              )}

              {weightPoints.length >= 2 && (
                <div className="h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart
                      data={weightPoints}
                      margin={{ top: 4, right: 8, bottom: 4, left: -20 }}
                    >
                      <defs>
                        <linearGradient id="weightFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={SERIES_COLOR.weight} stopOpacity={0.25} />
                          <stop offset="100%" stopColor={SERIES_COLOR.weight} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="date" {...axisStyle} minTickGap={40} />
                      <YAxis {...axisStyle} domain={["dataMin - 1", "dataMax + 1"]} width={44} />
                      <Tooltip {...tooltipStyle} />
                      <Area
                        type="monotone"
                        dataKey="trend"
                        stroke={SERIES_COLOR.weight}
                        strokeWidth={2.5}
                        fill="url(#weightFill)"
                        name="Trend"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
          </motion.section>

          {/* --- recent records ---------------------------------------------- */}
          {data && data.recentRecords.length > 0 && (
            <motion.section variants={item} aria-labelledby="records-heading">
              <Card>
                <CardHeader>
                  <CardTitle id="records-heading">Recent records</CardTitle>
                </CardHeader>
                <ul className="flex flex-col gap-2">
                  {data.recentRecords.slice(0, 5).map((record) => (
                    <li
                      key={record.id}
                      className="flex items-center justify-between gap-3 rounded-md px-2 py-2"
                    >
                      <span className="flex items-center gap-2 text-body text-text">
                        <Trophy className="h-4 w-4 text-accent-text" aria-hidden />
                        {record.exerciseName ?? "Exercise"}
                      </span>
                      <span className="tabular text-body text-text-secondary">
                        {record.value}
                        {record.repsAtValue ? ` × ${record.repsAtValue}` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
            </motion.section>
          )}

          {/* --- quick actions ---------------------------------------------- */}
          <motion.section variants={item} aria-labelledby="actions-heading">
            <h2 id="actions-heading" className="mb-3 text-h2">
              Quick actions
            </h2>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[
                { href: "/workouts/active", label: "Start workout", icon: Dumbbell },
                { href: "/progress", label: "Log weight", icon: Scale },
                { href: "/coach", label: "Ask the coach", icon: Bot },
                { href: "/progress/measurements", label: "Measurements", icon: TrendingUp },
              ].map(({ href, label, icon: Icon }) => (
                <Link key={label} href={href}>
                  <Card variant="interactive" className="flex h-full items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-surface-well text-accent-text">
                      <Icon className="h-5 w-5" aria-hidden />
                    </span>
                    <span className="text-body text-text">{label}</span>
                  </Card>
                </Link>
              ))}
            </div>
          </motion.section>

          {dashboard.isError && (
            <motion.div variants={item}>
              <EmptyState
                icon={<Flame className="h-8 w-8" />}
                title="Couldn't load your dashboard"
                description="We'll retry when you're back online, or try again now."
                action={<Button onClick={() => dashboard.refetch()}>Try again</Button>}
              />
            </motion.div>
          )}
        </motion.div>
      </PageShell>
    </>
  );
}
