import { api } from "@/lib/api/client";

/**
 * The training calendar.
 *
 * Served from the daily activity aggregate rather than by scanning sets, so a year of
 * history is one cheap query. The client's job is only to lay it out.
 *
 * Every date here is the user's *local* date, as the server stores it. That matters more
 * than it looks: a workout finished at 00:30 in Athens belongs to that day, and building
 * the grid from UTC timestamps would move it to the previous square.
 *
 * The helpers below are deliberately pure and separate from the page. A calendar is
 * almost entirely arithmetic — leading blanks, month boundaries, a relative colour scale
 * — and every one of those is a place to be off by one in a way that only shows up in
 * February, or in a month that starts on a Sunday.
 */

export type CalendarDay = {
  localDate: string;
  workoutCount: number;
  totalVolumeKg: string;
  durationSeconds: number;
};

/**
 * One completed session, as the history endpoint returns it.
 *
 * Fetched alongside the aggregate for the same month so a square can link to the workout
 * it represents. The aggregate carries no session ids — it is one row per day — which is
 * why the mobile calendar is not tappable at all. Here the second request is cheap and
 * the pointer is exact rather than guessed.
 */
export type CalendarSession = {
  id: string;
  name: string;
  localDate: string;
  totalVolumeKg: string;
  totalSets: number;
  exerciseCount: number;
  prCount: number;
  durationSeconds: number | null;
};

export const calendarKeys = {
  all: ["calendar"] as const,
  range: (from: string, to: string) => [...calendarKeys.all, "days", from, to] as const,
  sessions: (from: string, to: string) => [...calendarKeys.all, "sessions", from, to] as const,
};

export const calendarApi = {
  range: (from: string, to: string) =>
    api.get<CalendarDay[]>("/v1/workouts/sessions/calendar", { query: { from, to } }),

  /**
   * The month's sessions, for the day → session links.
   *
   * `limit` is the endpoint's maximum. A calendar month cannot hold more than 31 days of
   * training, so a second page would only ever mean several sessions on the same day,
   * and the first of those is the one a square links to anyway.
   */
  sessions: (from: string, to: string) =>
    api.get<{ items: CalendarSession[] }>("/v1/workouts/sessions", {
      query: { from, to, limit: 100 },
    }),
};

/** `2026-08-27`, from a Date, in local time rather than UTC. */
export function toLocalISO(date: Date): string {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

/** First and last day of the month containing `date`, as local ISO strings. */
export function monthBounds(date: Date): { from: string; to: string } {
  const first = new Date(date.getFullYear(), date.getMonth(), 1);
  // Day 0 of the next month is the last day of this one, and it handles February and
  // leap years without a table.
  const last = new Date(date.getFullYear(), date.getMonth() + 1, 0);
  return { from: toLocalISO(first), to: toLocalISO(last) };
}

export function shiftMonth(date: Date, delta: number): Date {
  // Anchored to the 1st before shifting: from the 31st, adding a month lands on the 1st
  // of the month after next, so a user paging through the year skips one entirely.
  return new Date(date.getFullYear(), date.getMonth() + delta, 1);
}

export type Cell = { date: string; day: number; inMonth: boolean };

/**
 * A six-week grid for the month, Monday first.
 *
 * Monday rather than Sunday because the app is built for Greece and the rest of Europe,
 * where the week starts on Monday and a Sunday-first calendar reads as an off-by-one.
 *
 * Always six rows, so the grid does not change height between months — a calendar that
 * grows and shrinks as you page through it makes the controls jump under the cursor.
 */
export function monthGrid(date: Date): Cell[] {
  const first = new Date(date.getFullYear(), date.getMonth(), 1);
  // `getDay()` is Sunday-based; this converts to Monday-based, where Monday is 0.
  const leading = (first.getDay() + 6) % 7;

  const cells: Cell[] = [];
  for (let index = 0; index < 42; index += 1) {
    const cursor = new Date(date.getFullYear(), date.getMonth(), 1 - leading + index);
    cells.push({
      date: toLocalISO(cursor),
      day: cursor.getDate(),
      inMonth: cursor.getMonth() === date.getMonth(),
    });
  }
  return cells;
}

/**
 * Training intensity for a day, on a 0-3 scale.
 *
 * Relative to the busiest day in view rather than an absolute volume, because "a heavy
 * day" means something different for a beginner and a powerlifter, and a fixed scale
 * would paint one of them permanently grey.
 */
export function intensity(day: CalendarDay | undefined, busiest: number): 0 | 1 | 2 | 3 {
  if (!day || day.workoutCount === 0) return 0;

  const volume = Number(day.totalVolumeKg);
  // A session with no volume — mobility, a run — still trained. It gets the lowest lit
  // level rather than reading as a rest day.
  if (!Number.isFinite(volume) || volume <= 0 || busiest <= 0) return 1;

  const share = volume / busiest;
  if (share > 0.66) return 3;
  if (share > 0.33) return 2;
  return 1;
}

/** The largest single-day volume in view, which the scale above is relative to. */
export function busiestVolume(days: readonly CalendarDay[]): number {
  return days.reduce((most, day) => {
    const volume = Number(day.totalVolumeKg);
    return Number.isFinite(volume) && volume > most ? volume : most;
  }, 0);
}

/** Days trained, total volume and total time for the month in view. */
export function monthTotals(days: readonly CalendarDay[]): {
  daysTrained: number;
  volumeKg: number;
  hours: number;
} {
  let daysTrained = 0;
  let volumeKg = 0;
  let seconds = 0;

  for (const day of days) {
    if (day.workoutCount > 0) daysTrained += 1;
    const volume = Number(day.totalVolumeKg);
    if (Number.isFinite(volume)) volumeKg += volume;
    seconds += day.durationSeconds;
  }

  return { daysTrained, volumeKg, hours: seconds / 3600 };
}

/**
 * The month's sessions, indexed by local date.
 *
 * A day can hold more than one — a morning lift and an evening run — so the value is a
 * list. The order the endpoint returns is newest first within a day, and it is kept:
 * clicking a square opens the most recent workout on it, which is the one a person
 * paging back through the month is thinking of.
 */
export function sessionsByDate(
  sessions: readonly CalendarSession[],
): Map<string, CalendarSession[]> {
  const map = new Map<string, CalendarSession[]>();
  for (const session of sessions) {
    const existing = map.get(session.localDate);
    if (existing) existing.push(session);
    else map.set(session.localDate, [session]);
  }
  return map;
}

/**
 * The longest run of consecutive trained days ending on or before `today`.
 *
 * Counted over the days actually returned, so it is a streak *within the month in view*
 * rather than an all-time figure — the page says as much next to it. Presenting a
 * windowed number as a lifetime streak is how a calendar tells someone they have lost a
 * streak they still have.
 */
export function longestStreak(days: readonly CalendarDay[]): number {
  const trained = new Set(days.filter((day) => day.workoutCount > 0).map((day) => day.localDate));
  if (trained.size === 0) return 0;

  let longest = 0;
  for (const date of trained) {
    // Only start counting from the beginning of a run, so each run is walked once.
    if (trained.has(previousDay(date))) continue;

    let length = 0;
    let cursor = date;
    while (trained.has(cursor)) {
      length += 1;
      cursor = nextDay(cursor);
    }
    if (length > longest) longest = length;
  }
  return longest;
}

/** `2026-03-01` → `2026-02-28`. Parsed as local, not UTC, to match every other date here. */
function previousDay(iso: string): string {
  return shiftDay(iso, -1);
}

function nextDay(iso: string): string {
  return shiftDay(iso, 1);
}

function shiftDay(iso: string, delta: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  // `new Date("2026-03-01")` is parsed as UTC and would be the previous day west of
  // Greenwich. The numeric constructor is local, which is what the rest of this file uses.
  return toLocalISO(new Date(year, month - 1, day + delta));
}
