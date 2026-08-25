import { api } from "@/lib/api/client";

/**
 * Weight, measurements and training statistics.
 *
 * The weight series is the one screen in the app that can actively mislead. Bodyweight
 * swings two kilos on water alone, so a chart of raw weigh-ins shows a sawtooth that
 * looks like progress reversing every other day — people quit over that graph. The server
 * therefore sends the smoothed trend alongside the dots, and both are drawn: the dots are
 * what happened, the line is what it means.
 */

export type WeightLog = {
  id: string;
  localDate: string;
  weightKg: string;
  trendWeightKg: string | null;
  bodyFatPct: string | null;
  measurementContext: string;
  source: string;
  note: string | null;
};

export type WeightPoint = {
  localDate: string;
  weightKg: string;
  trendKg: string;
};

export type GoalProjection = {
  targetWeightKg: string;
  weeklyRateKg: string;
  weeksRemaining: string | null;
  projectedDate: string | null;
  /** True when the trend heads away from the target, in which case no date is given. */
  isMovingAway: boolean;
};

export type WeightSeries = {
  points: WeightPoint[];
  latestWeightKg: string | null;
  latestTrendKg: string | null;
  changeKg: string | null;
  weeklyRateKg: string | null;
  projection: GoalProjection | null;
};

export type Measurement = {
  id: string;
  localDate: string;
  sites: Record<string, string>;
  note: string | null;
  waistToHipRatio: string | null;
};

export type SiteTrend = {
  site: string;
  firstValueCm: string;
  latestValueCm: string;
  changeCm: string;
  points: [string, string][];
};

export type MuscleVolumeBucket = {
  periodStart: string;
  periodEnd: string;
  volumeByMuscleGroup: Record<string, string>;
  totalVolumeKg: string;
  totalSets: number;
};

export type FrequencyBucket = {
  periodStart: string;
  periodEnd: string;
  workoutCount: number;
  totalVolumeKg: string;
  durationSeconds: number;
};

/** The sites the server accepts, in the order a person would measure them. */
export const MEASUREMENT_SITES = [
  "neck",
  "chest",
  "waist",
  "hips",
  "leftArm",
  "rightArm",
  "leftThigh",
  "rightThigh",
  "leftCalf",
  "rightCalf",
] as const;

export type MeasurementSite = (typeof MEASUREMENT_SITES)[number];

export const SITE_LABELS: Record<MeasurementSite, string> = {
  neck: "Neck",
  chest: "Chest",
  waist: "Waist",
  hips: "Hips",
  leftArm: "Left arm",
  rightArm: "Right arm",
  leftThigh: "Left thigh",
  rightThigh: "Right thigh",
  leftCalf: "Left calf",
  rightCalf: "Right calf",
};

export const progressKeys = {
  all: ["progress"] as const,
  weight: (days: number) => [...progressKeys.all, "weight", days] as const,
  measurements: () => [...progressKeys.all, "measurements"] as const,
  measurementSeries: () => [...progressKeys.all, "measurements", "series"] as const,
  volume: (weeks: number) => [...progressKeys.all, "volume", weeks] as const,
  frequency: (weeks: number) => [...progressKeys.all, "frequency", weeks] as const,
};

/** `from`/`to` are aliases on the server; the client sends ISO dates in local time. */
function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

export const progressApi = {
  weight: (days = 90) =>
    api.get<WeightSeries>("/v1/progress/weight", { query: { from: isoDaysAgo(days) } }),

  logWeight: (input: {
    weightKg: number;
    localDate?: string;
    bodyFatPct?: number | null;
    note?: string | null;
  }) => api.post<WeightLog>("/v1/progress/weight", input),

  deleteWeight: (logId: string) => api.delete<void>(`/v1/progress/weight/${logId}`),

  measurements: () => api.get<Measurement[]>("/v1/progress/measurements"),

  logMeasurement: (sites: Partial<Record<MeasurementSite, number>> & { localDate?: string }) =>
    api.post<Measurement>("/v1/progress/measurements", sites),

  measurementSeries: () =>
    api.get<{ trends: SiteTrend[] }>("/v1/progress/measurements/series"),

  volume: (weeks = 12) =>
    api.get<MuscleVolumeBucket[]>("/v1/progress/stats/volume", {
      query: { from: isoDaysAgo(weeks * 7) },
    }),

  frequency: (weeks = 12) =>
    api.get<FrequencyBucket[]>("/v1/progress/stats/frequency", {
      query: { from: isoDaysAgo(weeks * 7) },
    }),
};

/**
 * Which way a change should be read.
 *
 * Deliberately not "down is good". Someone gaining muscle wants the number rising, and an
 * app that paints their success red teaches them to distrust it. Direction is reported;
 * whether it is *wanted* is the goal's business, not this function's.
 */
export function changeDirection(change: string | null): "up" | "down" | "flat" {
  const value = parse(change);
  if (value === null || Math.abs(value) < 0.05) return "flat";
  return value > 0 ? "up" : "down";
}

/**
 * A decimal string, or null when there is nothing to read.
 *
 * `Number("")` is `0`, not `NaN`, so an absent value would otherwise render as "no
 * change" — a different claim entirely on a screen about whether anything changed.
 */
function parse(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** `+1.2 kg`, `−0.8 kg`, `—`. The sign carries the meaning, so it is never dropped. */
export function signedKg(change: string | null): string {
  const value = parse(change);
  if (value === null) return "—";
  if (Math.abs(value) < 0.05) return "0.0 kg";
  // A real minus sign, not a hyphen: at caption size a hyphen reads as a dash.
  return `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(1)} kg`;
}

/** `0.4 kg/week`, or null when there are too few weigh-ins for a rate to mean anything. */
export function weeklyRate(rate: string | null): string | null {
  const value = parse(rate);
  if (value === null || value === 0) return null;
  return `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(2)} kg/week`;
}

/**
 * Minimum and maximum across both the dots and the line, padded.
 *
 * Both series share one scale on purpose: drawing the trend on its own axis would let a
 * flat line sit beside wildly swinging dots, which is precisely the comparison the chart
 * exists to make.
 */
export function weightBounds(points: readonly WeightPoint[]): { min: number; max: number } {
  const values = points.flatMap((point) => [Number(point.weightKg), Number(point.trendKg)]);
  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length === 0) return { min: 0, max: 1 };

  const low = Math.min(...finite);
  const high = Math.max(...finite);
  // A flat run would otherwise be a zero-height band and divide by zero downstream.
  if (high - low < 1) return { min: low - 1, max: high + 1 };

  const pad = (high - low) * 0.1;
  return { min: low - pad, max: high + pad };
}
