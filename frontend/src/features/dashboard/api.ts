import { api } from "@/lib/api/client";

export type WeightPoint = {
  localDate: string;
  weightKg: string;
  trendKg: string;
};

export type WeightSeries = {
  points: WeightPoint[];
  latestWeightKg: string | null;
  latestTrendKg: string | null;
  changeKg: string | null;
  weeklyRateKg: string | null;
};

export type Streak = {
  current: number;
  longest: number;
  lastDate: string | null;
};

export type PeriodTotals = {
  workoutCount: number;
  totalVolumeKg: string;
  totalSets: number;
  durationSeconds: number;
  prCount: number;
};

export type PersonalRecord = {
  id: string;
  exerciseId: string;
  exerciseName?: string | null;
  recordType: string;
  value: string;
  repsAtValue: number | null;
  achievedOn: string;
};

export type Dashboard = {
  today: string;
  weight: WeightSeries;
  workoutStreak: Streak;
  thisWeek: PeriodTotals;
  lastWeek: PeriodTotals;
  recentRecords: PersonalRecord[];
  /** Null until the nutrition domain exists — never zeroes (docs/03). */
  nutrition: null;
};

export const dashboardKeys = {
  overview: ["dashboard", "overview"] as const,
};

export const dashboardApi = {
  overview: () => api.get<Dashboard>("/v1/progress/stats/overview"),
};

/**
 * Percentage change between two periods, or null when there is no baseline.
 *
 * Returning null rather than 0 or Infinity matters: "no change" and "nothing to
 * compare against" are different statements, and a tile that shows +0% for a first
 * week is telling the user something false.
 */
export function percentChange(current: number, previous: number): number | null {
  if (!Number.isFinite(current) || !Number.isFinite(previous) || previous === 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}
