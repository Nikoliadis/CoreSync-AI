import { api } from "@/lib/api/client";

/**
 * Badges, earned and not.
 *
 * The unearned ones matter more than the earned ones. A grid of grey padlocks tells you
 * nothing and reads as a paywall; the server sends `progress` and `currentValue` on every
 * entry precisely so an unearned badge can say "7 of 10 workouts" — which is a reason to
 * come back rather than a decoration.
 *
 * Tiers are presentational only. Gold is not harder than bronze, it is a different colour,
 * and the copy should never imply otherwise.
 */

export const TIERS = ["bronze", "silver", "gold"] as const;
export type Tier = (typeof TIERS)[number];

export const CATEGORIES = ["consistency", "volume", "strength", "milestone"] as const;
export type Category = (typeof CATEGORIES)[number];

export const CATEGORY_LABELS: Record<Category, string> = {
  consistency: "Consistency",
  volume: "Volume",
  strength: "Strength",
  milestone: "Milestones",
};

export type Achievement = {
  code: string;
  name: string;
  description: string;
  category: string;
  tier: string;
  threshold: string;
  earned: boolean;
  earnedAt: string | null;
  /** 0..1, carried on unearned entries too. */
  progress: string;
  currentValue: string;
};

export type AchievementList = {
  achievements: Achievement[];
  earnedCount: number;
  totalCount: number;
};

export const achievementKeys = {
  all: ["achievements"] as const,
  list: () => [...achievementKeys.all, "list"] as const,
};

export const achievementsApi = {
  list: () => api.get<AchievementList>("/v1/achievements"),

  /**
   * Ask the server to re-check.
   *
   * Evaluation also runs on a worker, so this is a nudge rather than the only path —
   * which is why the screen does not block on it or treat a failure as an error worth
   * showing. The badge appears a moment later either way.
   */
  evaluate: () => api.post<{ newlyEarned: Achievement[] }>("/v1/achievements/evaluate", {}),
};

/** Tier colours. Presentational only — gold is not harder to get than bronze. */
export const TIER_COLOURS: Record<Tier, string> = {
  bronze: "#B87333",
  silver: "#A8A9AD",
  gold: "#D4A017",
};

export function tierColour(tier: string): string {
  return TIER_COLOURS[tier as Tier] ?? TIER_COLOURS.bronze;
}

/**
 * How close, as a percentage, clamped.
 *
 * The server already clamps, but a client that trusts a remote number to be in range and
 * feeds it straight to a width style renders a bar out of its own container.
 */
export function progressPct(achievement: Achievement): number {
  const value = Number(achievement.progress);
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value)) * 100;
}

/** `7 of 10`, using whole numbers — "7.0 of 10.0 workouts" reads like a lab result. */
export function progressLabel(achievement: Achievement): string {
  const current = Number(achievement.currentValue);
  const threshold = Number(achievement.threshold);
  if (!Number.isFinite(current) || !Number.isFinite(threshold)) return "";

  // Large thresholds (volume in kg) are grouped; small ones are counts and are not.
  const format = (value: number) =>
    threshold >= 1000 ? Math.round(value).toLocaleString() : String(Math.round(value));

  return `${format(Math.min(current, threshold))} of ${format(threshold)}`;
}

/**
 * Earned first, then whatever is closest to being earned.
 *
 * Sorting unearned badges by progress is the whole point of the screen: the one you are
 * two workouts away from should be the one you see, not the one requiring a hundred.
 */
export function ranked(achievements: readonly Achievement[]): Achievement[] {
  return [...achievements].sort((a, b) => {
    if (a.earned !== b.earned) return a.earned ? -1 : 1;
    if (a.earned && b.earned) {
      // Most recent first among earned.
      return (b.earnedAt ?? "").localeCompare(a.earnedAt ?? "");
    }
    return Number(b.progress) - Number(a.progress);
  });
}

/** Group into the four categories, preserving each group's ranking. */
export function byCategory(
  achievements: readonly Achievement[],
): [Category, Achievement[]][] {
  return CATEGORIES.map((category) => [
    category,
    ranked(achievements.filter((item) => item.category === category)),
  ]).filter(([, items]) => (items as Achievement[]).length > 0) as [Category, Achievement[]][];
}
