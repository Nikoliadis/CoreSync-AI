import { api } from "@/lib/api/client";

/**
 * Nutrition, against the existing backend.
 *
 * One thing shapes every offline decision in this feature and is worth stating up front:
 * **nutrition mutations are not idempotent**. `POST /v1/nutrition/diary` takes no client
 * id — the server mints the entry — and there is no nutrition equivalent of
 * `/workouts/sessions/sync`. A queued write replayed after a failed flush would create a
 * second entry, not update the first.
 *
 * So reads are cached and work offline; writes require a connection and say so. That is
 * the opposite of the workout path, and the difference is the API's, not a shortcut here.
 */

export type MealType = "breakfast" | "lunch" | "dinner" | "snack";

export const MEAL_ORDER: readonly MealType[] = ["breakfast", "lunch", "dinner", "snack"];

export type Macros = {
  calories: string;
  proteinG: string;
  carbsG: string;
  fatG: string;
  alcoholG: string;
};

export type FoodServing = {
  id: string;
  label: string;
  grams: string;
  isDefault: boolean;
};

export type Food = {
  id: string;
  name: string;
  source: string;
  /** 1 curated · 2 official · 3 community · 4 the user's own. Tier 1 shows a badge. */
  trustTier: 1 | 2 | 3 | 4;
  isVerified: boolean;
  isCustom: boolean;
  isLiquid: boolean;
  caloriesPer100g: string;
  proteinPer100g: string;
  carbsPer100g: string;
  fatPer100g: string;
  alcoholPer100g: string;
  servings: FoodServing[];
};

export type Nutrient = {
  code: string;
  name: string;
  /** 'g' | 'mg' | 'mcg' | 'IU' — the unit a label prints. */
  unit: string;
  amountPer100g: string;
};

export type FoodDetail = { food: Food; nutrients: Nutrient[] };

export type DiaryEntry = {
  id: string;
  localDate: string;
  mealType: MealType;
  displayName: string;
  quantity: string;
  totalGrams: string;
  macros: Macros;
  foodId: string | null;
  recipeId: string | null;
  servingId: string | null;
  loggedAt: string | null;
};

export type MealTotals = { mealType: MealType; entries: number; macros: Macros };

export type Diary = {
  localDate: string;
  totals: Macros;
  waterMl: string;
  byMeal: MealTotals[];
  entries: DiaryEntry[];
  /** The targets in force on *that* day, not today's. Null when never set. */
  targets: Macros | null;
  remaining: Macros | null;
};

export type Water = { localDate: string; totalMl: string };

export type FoodPage = { items: Food[]; total: number };

export type DailySummary = {
  localDate: string;
  calories: string;
  proteinG: string;
  carbsG: string;
  fatG: string;
  alcoholG: string;
  waterMl: string;
  entryCount: number;
  targetCalories: string | null;
  targetProteinG: string | null;
};

export const nutritionKeys = {
  all: ["nutrition"] as const,
  diary: (on: string) => [...nutritionKeys.all, "diary", on] as const,
  search: (q: string) => [...nutritionKeys.all, "search", q] as const,
  recent: () => [...nutritionKeys.all, "recent"] as const,
  favourites: () => [...nutritionKeys.all, "favourites"] as const,
  food: (id: string) => [...nutritionKeys.all, "food", id] as const,
  water: (on: string) => [...nutritionKeys.all, "water", on] as const,
  history: (days: number) => [...nutritionKeys.all, "history", days] as const,
  streak: () => [...nutritionKeys.all, "streak"] as const,
};

export const nutritionApi = {
  diary: (on?: string) =>
    api.get<Diary>("/v1/nutrition/diary", { query: { on } }),

  search: (q: string, limit = 25) =>
    api.get<FoodPage>("/v1/nutrition/foods", { query: { q, limit } }),

  /**
   * What gets logged most.
   *
   * Derived from the diary rather than a separate table, and in practice this is where
   * most logging starts — people eat the same twenty things.
   */
  recent: () => api.get<FoodPage>("/v1/nutrition/foods/recent"),

  favourites: () => api.get<FoodPage>("/v1/nutrition/foods/favourites"),

  food: (id: string) => api.get<FoodDetail>(`/v1/nutrition/foods/${id}`),

  logFood: (input: {
    foodId: string;
    mealType: MealType;
    quantity: number;
    servingId?: string | null;
    localDate?: string;
  }) => api.post<DiaryEntry>("/v1/nutrition/diary", input),

  quickAdd: (input: {
    mealType: MealType;
    calories: number;
    proteinG?: number;
    carbsG?: number;
    fatG?: number;
    label?: string;
    localDate?: string;
  }) => api.post<DiaryEntry>("/v1/nutrition/diary/quick-add", input),

  /** Only what changed. The server leaves the rest alone. */
  editEntry: (
    entryId: string,
    changes: {
      quantity?: number;
      mealType?: MealType;
      servingId?: string | null;
      localDate?: string;
    },
  ) => api.patch<DiaryEntry>(`/v1/nutrition/diary/${entryId}`, changes),

  deleteEntry: (entryId: string) =>
    api.delete<void>(`/v1/nutrition/diary/${entryId}`),

  copyDay: (input: { sourceDate: string; targetDate: string; mealType?: MealType }) =>
    api.post<{ copied: number; targetDate: string }>("/v1/nutrition/diary/copy", input),

  water: (on?: string) => api.get<Water>("/v1/nutrition/water", { query: { on } }),

  logWater: (millilitres: number, localDate?: string) =>
    api.post<Water>("/v1/nutrition/water", { millilitres, localDate }),

  history: (days = 30) =>
    api
      .get<{ items: DailySummary[] }>("/v1/nutrition/history", { query: { days } })
      .then((page) => page.items),

  streak: () =>
    api.get<{ current: number; longest: number; lastDate: string | null }>(
      "/v1/nutrition/streak",
    ),
};

// ------------------------------------------------------------------ display
/** The API sends decimals as strings so nothing is lost in transit. Display rounds. */
export function kcal(value: string | null | undefined): number {
  return Math.round(Number(value ?? 0));
}

export function grams(value: string | null | undefined): number {
  return Math.round(Number(value ?? 0));
}

/** One decimal, but only when it says something — `116.0 g` reads worse than `116 g`. */
export function portion(value: string | null | undefined): string {
  const parsed = Number(value ?? 0);
  return Number.isInteger(parsed) ? String(parsed) : parsed.toFixed(1);
}

export const MEAL_LABEL_KEYS: Record<MealType, string> = {
  breakfast: "nutrition.breakfast",
  lunch: "nutrition.lunch",
  dinner: "nutrition.dinner",
  snack: "nutrition.snack",
};
