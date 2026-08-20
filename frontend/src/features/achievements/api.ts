import { api } from "@/lib/api/client";

export type Achievement = {
  code: string;
  name: string;
  description: string;
  category: string;
  tier: "bronze" | "silver" | "gold";
  threshold: string;
  earned: boolean;
  earnedAt: string | null;
  /** 0..1, carried so an unearned badge can show how close it is. */
  progress: string;
  currentValue: string;
};

export type AchievementList = {
  achievements: Achievement[];
  earnedCount: number;
  totalCount: number;
};

export const achievementKeys = {
  list: ["achievements"] as const,
};

export const achievementsApi = {
  list: () => api.get<AchievementList>("/v1/achievements"),
  evaluate: () =>
    api.post<{ newlyEarned: Achievement[] }>("/v1/achievements/evaluate", {}),
};

/**
 * Renders progress as "7 of 10" rather than a bare percentage.
 *
 * Large thresholds are abbreviated — "100,000 of 1,000,000 kg" is a wall of digits
 * that hides the very thing it is trying to communicate.
 */
export function progressLabel(achievement: Achievement): string {
  const current = Number(achievement.currentValue);
  const target = Number(achievement.threshold);
  if (!Number.isFinite(current) || !Number.isFinite(target)) return "";

  const abbreviate = (value: number) =>
    value >= 1_000_000
      ? `${(value / 1_000_000).toFixed(value % 1_000_000 === 0 ? 0 : 1)}M`
      : value >= 10_000
        ? `${Math.round(value / 1000)}k`
        : value.toLocaleString();

  return `${abbreviate(Math.min(current, target))} of ${abbreviate(target)}`;
}
