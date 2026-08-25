import { api } from "@/lib/api/client";

/**
 * Finished workouts, newest first.
 *
 * Keyset-paginated on `(localDate, id)` rather than by offset, because new sessions land
 * at the head of the list: an offset would drift mid-scroll and show the same workout
 * twice or skip one entirely.
 */

export type SessionSummary = {
  id: string;
  name: string;
  routineId: string | null;
  startedAt: string;
  completedAt: string | null;
  localDate: string;
  durationSeconds: number | null;
  totalVolumeKg: string;
  totalSets: number;
  totalReps: number;
  exerciseCount: number;
  prCount: number;
};

export type SessionHistoryPage = {
  items: SessionSummary[];
  nextCursor: string | null;
  hasMore: boolean;
};

export const sessionHistoryKeys = {
  all: ["session-history"] as const,
  list: () => [...sessionHistoryKeys.all, "list"] as const,
};

export const sessionHistoryApi = {
  page: (cursor?: string | null) =>
    api.get<SessionHistoryPage>("/v1/workouts/sessions", {
      query: cursor ? { limit: 20, cursor } : { limit: 20 },
    }),
};

/** `Today`, `Yesterday`, then the date. Relative labels beyond that stop helping. */
export function relativeDay(localDate: string, today = new Date()): string {
  const iso = (date: Date) =>
    [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0"),
    ].join("-");

  if (localDate === iso(today)) return "Today";

  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  if (localDate === iso(yesterday)) return "Yesterday";

  const [year, month, day] = localDate.split("-").map(Number);
  // `Number.isFinite`, not an undefined check: "not-a-date".split("-") yields three
  // parts that all parse to NaN, which builds a Date that renders as "Invalid Date" on
  // the row rather than failing loudly anywhere a developer would see it.
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) {
    return localDate;
  }

  // Parsed as local rather than UTC: `new Date("2026-08-25")` is midnight UTC, which is
  // the previous day for anyone west of Greenwich.
  return new Date(year!, month! - 1, day).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    ...(year === today.getFullYear() ? {} : { year: "numeric" }),
  });
}

/** `1h 12m`, `48m`, or a dash when the session never recorded one. */
export function duration(seconds: number | null): string {
  if (seconds === null || seconds <= 0) return "—";

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

/** Volume without trailing noise: `12,450 kg` reads, `12450.00` does not. */
export function volume(totalVolumeKg: string): string {
  const parsed = Number(totalVolumeKg);
  if (!Number.isFinite(parsed) || parsed <= 0) return "—";
  return `${Math.round(parsed).toLocaleString()} kg`;
}
