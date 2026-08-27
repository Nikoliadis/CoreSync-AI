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
 */

export type CalendarDay = {
  localDate: string;
  workoutCount: number;
  totalVolumeKg: string;
  durationSeconds: number;
};

export const calendarKeys = {
  all: ["calendar"] as const,
  range: (from: string, to: string) => [...calendarKeys.all, from, to] as const,
};

export const calendarApi = {
  range: (from: string, to: string) =>
    api.get<CalendarDay[]>("/v1/workouts/sessions/calendar", { query: { from, to } }),
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
 * grows and shrinks as you page through it makes the controls move under your thumb.
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
