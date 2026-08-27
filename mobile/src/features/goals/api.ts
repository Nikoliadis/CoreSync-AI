import { api } from "@/lib/api/client";

/**
 * The goal, and the nutrition targets derived from it.
 *
 * Two things people confuse and the API keeps apart: the *goal* is the intent ("lose fat,
 * 0.5 kg a week, to 78 kg") and the *targets* are the daily numbers computed from it.
 * Setting a goal does not move the targets on its own — recalculating does — which is why
 * this module exposes both and the screen runs them in sequence.
 *
 * Targets are versioned rather than overwritten, so changing one does not rewrite what
 * applied last month. That is what makes historical adherence answerable at all.
 */

export const GOAL_TYPES = [
  "lose_fat",
  "maintain",
  "gain_muscle",
  "recomp",
  "performance",
] as const;

export type GoalType = (typeof GOAL_TYPES)[number];

export const GOAL_LABELS: Record<GoalType, string> = {
  lose_fat: "Lose fat",
  maintain: "Maintain",
  gain_muscle: "Gain muscle",
  recomp: "Recomposition",
  performance: "Performance",
};

export const GOAL_BLURBS: Record<GoalType, string> = {
  lose_fat: "A calorie deficit, with protein held high to keep the muscle you have.",
  maintain: "Hold your weight. Targets track your intake rather than push it.",
  gain_muscle: "A modest surplus. Faster is mostly fat, not muscle.",
  recomp: "Eat at maintenance and train hard. Slow, and it does work.",
  performance: "Fuelled for output rather than for the scale.",
};

export type Goal = {
  id: string;
  goalType: GoalType;
  targetWeightKg: string | null;
  weeklyRateKg: string | null;
  targetDate: string | null;
  startedOn: string;
  endedOn: string | null;
};

export type NutritionTarget = {
  id: string;
  effectiveFrom: string;
  effectiveTo: string | null;
  calories: string;
  proteinG: string;
  carbsG: string;
  fatG: string;
  fiberG: string | null;
  waterMl: string;
  source: string;
  rationale: string | null;
};

export type TargetCalculation = {
  target: NutritionTarget;
  /** Mifflin-St Jeor, kcal/day. */
  bmr: string;
  tdee: string;
  /**
   * True when the computed deficit fell below the safety floor and was raised to meet it.
   *
   * Worth surfacing rather than hiding: it means the rate asked for is not achievable
   * safely at this bodyweight, and the app quietly gave a different number than requested.
   */
  wasClampedToFloor: boolean;
};

export const goalKeys = {
  all: ["goals"] as const,
  me: () => [...goalKeys.all, "me"] as const,
  targetHistory: () => [...goalKeys.all, "target-history"] as const,
};

export const goalsApi = {
  me: () =>
    api.get<{
      goal: Goal | null;
      targets: NutritionTarget | null;
      profile: { heightCm: string | null; dateOfBirth: string | null; gender: string | null } | null;
    }>("/v1/users/me"),

  setGoal: (input: {
    goalType: GoalType;
    targetWeightKg?: number | null;
    weeklyRateKg?: number | null;
    targetDate?: string | null;
  }) => api.post<Goal>("/v1/users/me/goals", input),

  recalculateTargets: () =>
    api.post<TargetCalculation>("/v1/users/me/targets/recalculate", {}),

  setTargets: (input: {
    calories: number;
    proteinG: number;
    carbsG: number;
    fatG: number;
    fiberG?: number | null;
    waterMl?: number | null;
  }) => api.put<NutritionTarget>("/v1/users/me/targets", input),

  targetHistory: () => api.get<NutritionTarget[]>("/v1/users/me/targets/history"),
};

/**
 * Whether a weekly rate is sane for this goal.
 *
 * Not a server rule — the server clamps calories at 1200 and leaves the rate alone — but
 * the honest thing to say before somebody commits to it. Roughly 1% of bodyweight per
 * week is the usual ceiling before losses stop being mostly fat, and gaining faster than
 * ~0.5 kg/week is mostly not muscle.
 */
export function rateWarning(
  goalType: GoalType,
  weeklyRateKg: number | null,
  currentWeightKg: number | null,
): string | null {
  if (weeklyRateKg === null || weeklyRateKg === 0) return null;
  const rate = Math.abs(weeklyRateKg);

  if (goalType === "lose_fat") {
    const ceiling = currentWeightKg ? currentWeightKg * 0.01 : 1.0;
    if (rate > ceiling) {
      return `Losing more than ${ceiling.toFixed(1)} kg a week tends to cost muscle as well as fat.`;
    }
    return null;
  }

  if (goalType === "gain_muscle" && rate > 0.5) {
    return "Gaining faster than 0.5 kg a week is mostly fat. Slower is not worse.";
  }
  return null;
}

/**
 * Turn the magnitude the field collects into the signed rate the server stores.
 *
 * The input asks for "0.5 kg a week" rather than "-0.5 to lose", because the double
 * negative is what people mistype. That leaves the sign to us, and getting it wrong is
 * silent and serious: a positive rate on a fat-loss goal makes the server compute a
 * *surplus*, so somebody who asked to lose weight is told to eat more.
 */
export function signedWeeklyRate(goalType: GoalType, magnitude: number | null): number | null {
  if (magnitude === null || !Number.isFinite(magnitude) || magnitude === 0) return null;
  const size = Math.abs(magnitude);
  return goalType === "lose_fat" ? -size : size;
}

/** `78.0 kg by 12 Mar`, `78.0 kg`, or null when the goal names no destination. */
export function goalSummary(goal: Goal | null): string | null {
  if (!goal) return null;
  if (goal.goalType === "maintain") return "Holding steady";

  const weight = goal.targetWeightKg ? `${Number(goal.targetWeightKg).toFixed(1)} kg` : null;
  if (!weight) return GOAL_LABELS[goal.goalType];
  if (!goal.targetDate) return weight;

  return `${weight} by ${goal.targetDate}`;
}

/** Rounded whole numbers for display. Grams to one decimal is false precision. */
export function macroSplit(target: NutritionTarget | null): {
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
} | null {
  if (!target) return null;
  return {
    calories: Math.round(Number(target.calories)),
    protein: Math.round(Number(target.proteinG)),
    carbs: Math.round(Number(target.carbsG)),
    fat: Math.round(Number(target.fatG)),
  };
}
