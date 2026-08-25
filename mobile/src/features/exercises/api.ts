import { api } from "@/lib/api/client";

/**
 * The exercise catalogue, from the backend.
 *
 * The server is the source of truth — this is a read-through cache, never a second
 * catalogue. Rows land in `cached_exercises`, which has existed in the schema since the
 * first migration and until now was never written to. What that buys is the picker still
 * working in a basement, which is the one place it matters.
 */

export type MuscleRef = {
  id: string;
  slug: string;
  name: string;
  groupSlug: string | null;
  role: string | null;
  contributionPct: number | null;
};

export type Exercise = {
  id: string;
  slug: string;
  name: string;
  categorySlug: string | null;
  loggingType: string;
  difficulty: "beginner" | "intermediate" | "advanced";
  forceType: string | null;
  mechanic: string | null;
  isUnilateral: boolean;
  isVerified: boolean;
  isCustom: boolean;
  isFavorite: boolean;
  muscles: MuscleRef[];
  equipment: string[];
};

export type ExercisePage = {
  items: Exercise[];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
};

export type MuscleGroup = { id: string; slug: string; name: string };
export type Equipment = { id: string; slug: string; name: string; isHomeAvailable: boolean };

export type ExerciseFilters = {
  q?: string;
  muscleGroup?: string;
  equipment?: string;
  difficulty?: string;
  favoritesOnly?: boolean;
};

/** A page at a time. The catalogue is ~274 rows and there is no reason to pull it whole. */
export const PAGE_SIZE = 30;

export const exerciseKeys = {
  all: ["exercises"] as const,
  list: (filters: ExerciseFilters) => [...exerciseKeys.all, "list", filters] as const,
  muscleGroups: () => [...exerciseKeys.all, "muscle-groups"] as const,
  equipment: () => [...exerciseKeys.all, "equipment"] as const,
};

export const exercisesApi = {
  search: (filters: ExerciseFilters, offset = 0) =>
    api.get<ExercisePage>("/v1/exercises", {
      query: {
        q: filters.q,
        muscle_group: filters.muscleGroup,
        equipment: filters.equipment,
        difficulty: filters.difficulty,
        favoritesOnly: filters.favoritesOnly,
        limit: PAGE_SIZE,
        offset,
      },
    }),

  muscleGroups: () => api.get<MuscleGroup[]>("/v1/exercises/meta/muscle-groups"),

  equipment: () => api.get<Equipment[]>("/v1/exercises/meta/equipment"),
};

/** The primary mover, for the one line of detail a picker row has room for. */
export function primaryMuscle(exercise: Exercise): string | null {
  const primary = exercise.muscles.find((muscle) => muscle.role === "primary");
  return (primary ?? exercise.muscles[0])?.name ?? null;
}

export function equipmentLabel(exercise: Exercise): string | null {
  if (exercise.equipment.length === 0) return null;
  // Slugs come back as `barbell`, `ez_bar`. Rendered as written they look like
  // database rows rather than words.
  return exercise.equipment
    .map((slug) => slug.replace(/_/g, " "))
    .join(", ");
}
