import { api } from "@/lib/api/client";

/**
 * Trust tier, lowest number wins. 1 is hand-checked and earns the "Verified" badge;
 * 4 is a food the user typed in themselves. The badge is half the mitigation for bad
 * food data — the other half is that search ranks by this before anything else.
 */
export type TrustTier = 1 | 2 | 3 | 4;

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
  trustTier: TrustTier;
  isVerified: boolean;
  isCustom: boolean;
  isLiquid: boolean;
  caloriesPer100g: string;
  proteinPer100g: string;
  carbsPer100g: string;
  fatPer100g: string;
  /** Ethanol, at 7 kcal/g. Zero for everything that is not a drink. */
  alcoholPer100g: string;
  servings: FoodServing[];
};

export type MealType = "breakfast" | "lunch" | "dinner" | "snack";

export const MEAL_ORDER: MealType[] = ["breakfast", "lunch", "dinner", "snack"];

export const MEAL_LABELS: Record<MealType, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snacks",
};

export type Macros = {
  calories: string;
  proteinG: string;
  carbsG: string;
  fatG: string;
  alcoholG: string;
};

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

export type MealTotals = {
  mealType: MealType;
  entries: number;
  macros: Macros;
};

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

export type Water = {
  localDate: string;
  totalMl: string;
};

export type FoodSearchResult = {
  items: Food[];
  total: number;
};

export type LogFoodInput = {
  foodId: string;
  mealType: MealType;
  /** Servings when `servingId` is set, grams otherwise. */
  quantity: number;
  servingId?: string | null;
  localDate?: string;
};

export type QuickAddInput = {
  mealType: MealType;
  calories: number;
  proteinG?: number;
  carbsG?: number;
  fatG?: number;
  label?: string;
  localDate?: string;
};

export type CreateFoodInput = {
  name: string;
  caloriesPer100g: number;
  proteinPer100g?: number;
  carbsPer100g?: number;
  fatPer100g?: number;
  alcoholPer100g?: number;
  isLiquid?: boolean;
  servings?: { label: string; grams: number }[];
};

export type RecipeIngredient = {
  id: string;
  foodId: string;
  foodName: string;
  grams: string;
};

export type Recipe = {
  id: string;
  name: string;
  servingsCount: string;
  notes: string | null;
  ingredients: RecipeIngredient[];
  /** Computed on read from the current ingredient macros, never stored. */
  total: Macros;
  perServing: Macros;
  /**
   * An ingredient's food is gone. The totals under-report while this is set, so the UI
   * says so rather than showing a confidently wrong number.
   */
  hasMissingIngredients: boolean;
};

export type SaveRecipeInput = {
  name: string;
  servingsCount: number;
  notes?: string | null;
  /** The complete list, every time — the API replaces rather than patches. */
  ingredients: { foodId: string; grams: number }[];
};

export type DailySummary = {
  localDate: string;
  calories: string;
  proteinG: string;
  carbsG: string;
  fatG: string;
  alcoholG: string;
  waterMl: string;
  /** Zero means the day was logged and then emptied; absent means never logged. */
  entryCount: number;
  targetCalories: string | null;
  targetProteinG: string | null;
};

export type NutritionStreak = {
  current: number;
  longest: number;
  lastDate: string | null;
};

export type EditEntryInput = {
  quantity?: number;
  mealType?: MealType;
  servingId?: string | null;
  localDate?: string;
};

export type NutrientRow = {
  code: string;
  name: string;
  /** 'g' | 'mg' | 'mcg' | 'IU' — the unit a label prints. */
  unit: string;
  amountPer100g: string;
};

export type FoodDetail = {
  food: Food;
  /** Only what the source measured. Most community rows carry a handful, not all. */
  nutrients: NutrientRow[];
};

export const nutritionKeys = {
  all: ["nutrition"] as const,
  diary: (on?: string) => [...nutritionKeys.all, "diary", on ?? "today"] as const,
  water: (on?: string) => [...nutritionKeys.all, "water", on ?? "today"] as const,
  search: (q: string) => [...nutritionKeys.all, "search", q] as const,
  recent: () => [...nutritionKeys.all, "recent"] as const,
  recipes: () => [...nutritionKeys.all, "recipes"] as const,
  recipe: (id: string) => [...nutritionKeys.all, "recipe", id] as const,
  favourites: () => [...nutritionKeys.all, "favourites"] as const,
  history: (days: number) => [...nutritionKeys.all, "history", days] as const,
  streak: () => [...nutritionKeys.all, "streak"] as const,
  food: (id: string) => [...nutritionKeys.all, "food", id] as const,
};

export const nutritionApi = {
  search: (q: string, limit = 25) =>
    api.get<FoodSearchResult>(
      `/v1/nutrition/foods?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),

  /**
   * What they log often, derived from the diary.
   *
   * This is the empty state of the search screen and, in practice, where most logging
   * starts: people eat the same twenty things.
   */
  recent: () => api.get<FoodSearchResult>("/v1/nutrition/foods/recent"),

  byBarcode: (barcode: string) =>
    api.get<Food>(`/v1/nutrition/foods/barcode/${encodeURIComponent(barcode)}`),

  createFood: (input: CreateFoodInput) => api.post<Food>("/v1/nutrition/foods", input),

  diary: (on?: string) =>
    api.get<Diary>(on ? `/v1/nutrition/diary?on=${on}` : "/v1/nutrition/diary"),

  logFood: (input: LogFoodInput) => api.post<DiaryEntry>("/v1/nutrition/diary", input),

  quickAdd: (input: QuickAddInput) =>
    api.post<DiaryEntry>("/v1/nutrition/diary/quick-add", input),

  deleteEntry: (entryId: string) => api.delete<void>(`/v1/nutrition/diary/${entryId}`),

  /** Send only what changed — the server leaves the rest alone. */
  editEntry: (entryId: string, input: EditEntryInput) =>
    api.patch<DiaryEntry>(`/v1/nutrition/diary/${entryId}`, input),

  copyDay: (input: { sourceDate: string; targetDate: string; mealType?: MealType }) =>
    api.post<{ copied: number; targetDate: string }>("/v1/nutrition/diary/copy", input),

  water: (on?: string) =>
    api.get<Water>(on ? `/v1/nutrition/water?on=${on}` : "/v1/nutrition/water"),

  logWater: (millilitres: number, localDate?: string) =>
    api.post<Water>("/v1/nutrition/water", { millilitres, localDate }),

  recipes: () =>
    api.get<{ items: Recipe[] }>("/v1/nutrition/recipes").then((data) => data.items),

  recipe: (id: string) => api.get<Recipe>(`/v1/nutrition/recipes/${id}`),

  createRecipe: (input: SaveRecipeInput) =>
    api.post<Recipe>("/v1/nutrition/recipes", input),

  updateRecipe: (id: string, input: SaveRecipeInput) =>
    api.put<Recipe>(`/v1/nutrition/recipes/${id}`, input),

  deleteRecipe: (id: string) => api.delete<void>(`/v1/nutrition/recipes/${id}`),

  logRecipe: (id: string, input: { mealType: MealType; servings: number; localDate?: string }) =>
    api.post<DiaryEntry>(`/v1/nutrition/recipes/${id}/log`, input),

  updateFood: (id: string, input: CreateFoodInput) =>
    api.put<Food>(`/v1/nutrition/foods/${id}`, input),

  deleteFood: (id: string) => api.delete<void>(`/v1/nutrition/foods/${id}`),

  favourites: () =>
    api.get<FoodSearchResult>("/v1/nutrition/foods/favourites").then((r) => r.items),

  addFavourite: (id: string) => api.put<void>(`/v1/nutrition/foods/${id}/favourite`, {}),

  removeFavourite: (id: string) => api.delete<void>(`/v1/nutrition/foods/${id}/favourite`),

  submitFood: (id: string, note?: string) =>
    api.post<{ id: string; status: string }>(`/v1/nutrition/foods/${id}/submit`, { note }),

  history: (days = 30) =>
    api
      .get<{ items: DailySummary[] }>(`/v1/nutrition/history?days=${days}`)
      .then((r) => r.items),

  streak: () => api.get<NutritionStreak>("/v1/nutrition/streak"),

  food: (id: string) => api.get<FoodDetail>(`/v1/nutrition/foods/${id}`),
};
