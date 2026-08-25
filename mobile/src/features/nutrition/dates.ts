/**
 * Diary dates.
 *
 * A diary day is the *user's* local day, never UTC. `toISOString()` at 01:00 in Athens
 * returns the previous date, which would file breakfast under yesterday — the same class
 * of bug the backend avoids by storing `local_date` as a date in the user's timezone.
 */

/** Today, in the device's timezone, as the API's `YYYY-MM-DD`. */
export function localToday(): string {
  return toLocalISO(new Date());
}

export function toLocalISO(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

export function shiftDate(iso: string, days: number): string {
  // Parsed at local midnight rather than as a bare date, which JS treats as UTC and
  // would shift the result by a day for anyone west of Greenwich.
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  return toLocalISO(date);
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

/** Logging ahead is meaningless, so the diary does not scroll past today. */
export function isFuture(iso: string): boolean {
  return iso > localToday();
}
