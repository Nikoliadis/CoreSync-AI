import { api } from "@/lib/api/client";

/**
 * The home screen's data.
 *
 * Deliberately assembled from the endpoints that already exist rather than asking for a
 * new aggregate one. Each of these is independently cached and independently useful, so
 * a slow diary does not hold up the streak, and the screen fills in as answers arrive
 * instead of waiting for the slowest.
 */

export type Macros = {
  calories: string;
  proteinG: string;
  carbsG: string;
  fatG: string;
  alcoholG: string;
};

export type Diary = {
  localDate: string;
  totals: Macros;
  waterMl: string;
  targets: Macros | null;
  remaining: Macros | null;
  entries: { id: string; displayName: string; mealType: string; macros: Macros }[];
};

export type NutritionStreak = {
  current: number;
  longest: number;
  lastDate: string | null;
};

export type WeightPoint = {
  localDate: string;
  weightKg: string;
  trendWeightKg: string | null;
};

export type ActiveSession = {
  id: string;
  name: string;
  status: string;
  startedAt: string;
  totalSets: number;
  totalVolumeKg: string;
};

export const dashboardKeys = {
  all: ["dashboard"] as const,
  diary: () => [...dashboardKeys.all, "diary"] as const,
  streak: () => [...dashboardKeys.all, "streak"] as const,
  weight: () => [...dashboardKeys.all, "weight"] as const,
  active: () => [...dashboardKeys.all, "active-session"] as const,
};

export const dashboardApi = {
  diary: () => api.get<Diary>("/v1/nutrition/diary"),

  streak: () => api.get<NutritionStreak>("/v1/nutrition/streak"),

  latestWeight: async (): Promise<WeightPoint | null> => {
    const data = await api.get<{ items: WeightPoint[] }>("/v1/progress/weight", {
      query: { limit: 1 },
    });
    return data.items[0] ?? null;
  },

  /** Null rather than an error when nothing is in progress — that is the normal case. */
  activeSession: async (): Promise<ActiveSession | null> => {
    try {
      return await api.get<ActiveSession>("/v1/workouts/sessions/active");
    } catch {
      return null;
    }
  },
};
