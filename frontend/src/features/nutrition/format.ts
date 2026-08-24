import type { Macros } from "./api";

/**
 * The API sends decimals as strings so nothing is lost in transit. Display rounds;
 * arithmetic never happens here — the server owns every total in the diary.
 */
export function kcal(value: string | null | undefined): number {
  return Math.round(Number(value ?? 0));
}

export function grams(value: string | null | undefined): number {
  return Math.round(Number(value ?? 0));
}

/** One decimal, but only when it says something. `116.0 g` reads worse than `116 g`. */
export function portion(value: string | null | undefined): string {
  const n = Number(value ?? 0);
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

export type MacroSlot = {
  key: "protein" | "carbs" | "fat";
  label: string;
  grams: number;
  /** A chart token, so the three macros keep the same colours everywhere. */
  color: string;
};

export function macroSlots(macros: Macros | null | undefined): MacroSlot[] {
  return [
    {
      key: "protein",
      label: "Protein",
      grams: grams(macros?.proteinG),
      color: "var(--color-chart-1)",
    },
    {
      key: "carbs",
      label: "Carbs",
      grams: grams(macros?.carbsG),
      color: "var(--color-chart-2)",
    },
    { key: "fat", label: "Fat", grams: grams(macros?.fatG), color: "var(--color-chart-3)" },
  ];
}

/**
 * Remaining calories, or null when no target is set.
 *
 * Null rather than zero: someone who has never set a target has not "used up" their
 * allowance, and showing 0 left would read as a failure they never signed up for.
 */
export function remainingKcal(remaining: Macros | null): number | null {
  return remaining ? kcal(remaining.calories) : null;
}

/** Today in the browser's timezone, as the API's `YYYY-MM-DD`. */
export function localToday(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

export function shiftDate(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

export function friendlyDate(iso: string): string {
  const today = localToday();
  if (iso === today) return "Today";
  if (iso === shiftDate(today, -1)) return "Yesterday";
  if (iso === shiftDate(today, 1)) return "Tomorrow";
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}
