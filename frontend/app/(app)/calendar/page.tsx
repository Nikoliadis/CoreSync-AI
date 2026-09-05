"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { StatTile } from "@/components/ui/stat-tile";
import {
  busiestVolume,
  type CalendarDay,
  calendarApi,
  calendarKeys,
  type CalendarSession,
  intensity,
  longestStreak,
  monthBounds,
  monthGrid,
  monthTotals,
  sessionsByDate,
  shiftMonth,
  toLocalISO,
} from "@/features/workouts/calendar-api";

/**
 * Which days you trained, as a month at a glance.
 *
 * The value is the pattern rather than any single day — three weeks of Tuesdays and
 * Thursdays with nothing at the weekend is a fact about somebody's life that no list of
 * sessions makes visible.
 *
 * Two requests rather than one: the aggregate paints the heatmap, and the month's
 * sessions turn each lit square into a link. The mobile calendar has only the first and
 * is deliberately not tappable as a result — a square there could only guess which
 * workout to open. Here the pointer is exact.
 *
 * What this page does *not* do is plan. Scheduling ahead needs planned-session endpoints
 * that do not exist, and a calendar that lets you place a workout in the future and then
 * silently forgets it is worse than one that only shows the past.
 */
export default function CalendarPage() {
  const [month, setMonth] = useState(() => new Date());
  const { from, to } = monthBounds(month);

  const days = useQuery({
    queryKey: calendarKeys.range(from, to),
    queryFn: () => calendarApi.range(from, to),
  });

  const sessions = useQuery({
    queryKey: calendarKeys.sessions(from, to),
    queryFn: () => calendarApi.sessions(from, to),
  });

  const byDate = useMemo(() => {
    const map = new Map<string, CalendarDay>();
    for (const day of days.data ?? []) map.set(day.localDate, day);
    return map;
  }, [days.data]);

  const sessionMap = useMemo(
    () => sessionsByDate(sessions.data?.items ?? []),
    [sessions.data],
  );

  const cells = useMemo(() => monthGrid(month), [month]);
  const busiest = busiestVolume(days.data ?? []);
  const totals = monthTotals(days.data ?? []);
  const streak = longestStreak(days.data ?? []);
  const today = toLocalISO(new Date());

  const monthLabel = new Intl.DateTimeFormat("en-GB", {
    month: "long",
    year: "numeric",
  }).format(month);

  // Derived from the locale rather than listed, so the labels stay correct if the app
  // ever renders in Greek here as it already does on mobile. 2026-01-05 was a Monday.
  const weekdays = useMemo(() => {
    const formatter = new Intl.DateTimeFormat("en-GB", { weekday: "short" });
    return Array.from({ length: 7 }, (_, index) =>
      formatter.format(new Date(2026, 0, 5 + index)),
    );
  }, []);

  const isCurrentMonth =
    month.getFullYear() === new Date().getFullYear() && month.getMonth() === new Date().getMonth();

  return (
    <>
      <TopBar title="Calendar" />

      <PageShell>
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile label="Days trained" value={totals.daysTrained} />
          <StatTile label="Volume" value={Math.round(totals.volumeKg).toLocaleString()} unit="kg" />
          <StatTile label="Time" value={totals.hours.toFixed(1)} unit="h" />
          <StatTile label="Best streak" value={streak} unit={streak === 1 ? "day" : "days"} />
        </div>

        <div className="rounded-lg border border-border bg-surface p-4 lg:p-6">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                aria-label="Previous month"
                onClick={() => setMonth((current) => shiftMonth(current, -1))}
              >
                <ChevronLeft className="size-4" aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Next month"
                onClick={() => setMonth((current) => shiftMonth(current, 1))}
              >
                <ChevronRight className="size-4" aria-hidden />
              </Button>
            </div>

            <h2 className="text-h3 text-text">{monthLabel}</h2>

            {/* Kept in the layout when it does nothing, so the month title does not
                shift sideways as you page in and out of the current month. */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setMonth(new Date())}
              disabled={isCurrentMonth}
            >
              Today
            </Button>
          </div>

          <div className="mb-2 grid grid-cols-7 gap-1.5 lg:gap-2">
            {weekdays.map((label) => (
              // Hidden from screen readers: each square already announces its full date,
              // and a column header read as "Mon" adds nothing to "Monday 3 August".
              <div key={label} aria-hidden className="text-center text-caption text-text-muted">
                {label}
              </div>
            ))}
          </div>

          {days.isLoading ? (
            <div className="grid grid-cols-7 gap-1.5 lg:gap-2">
              {Array.from({ length: 42 }).map((_, index) => (
                <Skeleton key={index} className="aspect-square rounded-md" />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-7 gap-1.5 lg:gap-2">
              {cells.map((cell) => (
                <DayCell
                  key={cell.date}
                  date={cell.date}
                  day={cell.day}
                  inMonth={cell.inMonth}
                  isToday={cell.date === today}
                  aggregate={byDate.get(cell.date)}
                  sessions={sessionMap.get(cell.date) ?? []}
                  level={intensity(byDate.get(cell.date), busiest)}
                />
              ))}
            </div>
          )}

          <Legend />
        </div>

        {!days.isLoading && totals.daysTrained === 0 && (
          <EmptyState
            className="mt-6"
            icon={<CalendarDays className="size-6" />}
            title="Nothing logged this month"
            description="Finish a workout and it appears here the same day."
            action={
              <Button asChild>
                <Link href="/workouts">Start a workout</Link>
              </Button>
            }
          />
        )}
      </PageShell>
    </>
  );
}

/**
 * One square.
 *
 * A link when there is a session behind it and a plain div otherwise, rather than a
 * disabled button: a control that looks interactive and does nothing is the single most
 * common complaint about calendar heatmaps.
 */
function DayCell({
  date,
  day,
  inMonth,
  isToday,
  aggregate,
  sessions,
  level,
}: {
  date: string;
  day: number;
  inMonth: boolean;
  isToday: boolean;
  aggregate: CalendarDay | undefined;
  sessions: CalendarSession[];
  level: 0 | 1 | 2 | 3;
}) {
  const readableDate = new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(new Date(...isoParts(date)));

  const label = aggregate?.workoutCount
    ? `${readableDate}: ${aggregate.workoutCount} ${
        aggregate.workoutCount === 1 ? "workout" : "workouts"
      }, ${Math.round(Number(aggregate.totalVolumeKg) || 0).toLocaleString()} kg`
    : `${readableDate}: rest day`;

  // One hue at four opacities. A rainbow scale reads as four unrelated categories
  // rather than as "more", and fails for the ~8% of men with colour-vision deficiency.
  const fill = [
    "bg-surface-well",
    "bg-accent/25",
    "bg-accent/60",
    "bg-accent",
  ][level];

  const content = (
    <>
      <span className={level === 3 ? "text-accent-ink" : "text-text-muted"}>{day}</span>
      {sessions.length > 1 && (
        <span
          aria-hidden
          className={`text-caption ${level === 3 ? "text-accent-ink" : "text-text-muted"}`}
        >
          ×{sessions.length}
        </span>
      )}
    </>
  );

  const shared = [
    "flex aspect-square flex-col items-center justify-center rounded-md text-body tabular-nums",
    fill,
    inMonth ? "opacity-100" : "opacity-30",
    isToday ? "ring-2 ring-accent-text ring-offset-1 ring-offset-surface" : "",
  ].join(" ");

  if (sessions.length === 0) {
    return (
      <div className={shared} aria-label={label} role="img">
        {content}
      </div>
    );
  }

  return (
    <Link
      href={`/workouts/${sessions[0].id}`}
      aria-label={`${label}. Open ${sessions[0].name}`}
      className={`${shared} transition hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-text`}
    >
      {content}
    </Link>
  );
}

function Legend() {
  return (
    <div className="mt-4 flex items-center justify-end gap-2 text-caption text-text-muted">
      <span>Less</span>
      {["bg-surface-well", "bg-accent/25", "bg-accent/60", "bg-accent"].map((fill) => (
        <span key={fill} aria-hidden className={`size-3 rounded-sm ${fill}`} />
      ))}
      <span>More</span>
    </div>
  );
}

/** `2026-08-27` → `[2026, 7, 27]`, for the local-time Date constructor. */
function isoParts(iso: string): [number, number, number] {
  const [year, month, day] = iso.split("-").map(Number);
  return [year, month - 1, day];
}
