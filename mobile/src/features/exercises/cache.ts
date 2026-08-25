/**
 * A read-through cache of the exercise catalogue.
 *
 * Not a second source of truth. Every row here arrived from the API and is replaced by
 * whatever the API says next; nothing is ever created locally, and there is no write
 * path back. What it exists for is the basement: docs/08 §1 says every write works
 * offline, and a picker that cannot list an exercise makes the whole workout screen
 * unusable regardless of how well the writes behave.
 *
 * The table has been in the schema since the first migration and until now nothing wrote
 * to it.
 */

import { openDatabase } from "@/offline/database";

import type { Exercise, ExerciseFilters } from "./api";

type CachedRow = { id: string; payload: string; cached_at: number };

/**
 * Store a page of results.
 *
 * Upsert rather than replace-all: results arrive filtered and paginated, so wiping the
 * table on every search would leave the cache holding only the last thing looked at —
 * which is the opposite of useful when the signal drops.
 */
export async function cacheExercises(exercises: readonly Exercise[]): Promise<void> {
  if (exercises.length === 0) return;
  const database = await openDatabase();
  const now = Date.now();

  await database.withTransactionAsync(async () => {
    for (const exercise of exercises) {
      await database.runAsync(
        `INSERT INTO cached_exercises (id, payload, cached_at)
         VALUES (?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, cached_at = excluded.cached_at`,
        exercise.id,
        JSON.stringify(exercise),
        now,
      );
    }
  });
}

/**
 * Search what has been cached.
 *
 * Filtering happens in TypeScript rather than SQL because the payload is a JSON blob and
 * the catalogue is a few hundred rows — a query planner has nothing to offer at this
 * size, and matching the server's filter semantics in SQL would be a second
 * implementation to keep in step.
 */
export async function searchCached(
  filters: ExerciseFilters,
  limit: number,
): Promise<Exercise[]> {
  const database = await openDatabase();
  const rows = await database.getAllAsync<CachedRow>(
    "SELECT * FROM cached_exercises ORDER BY cached_at DESC",
  );

  const needle = filters.q?.trim().toLowerCase();
  const matches: Exercise[] = [];

  for (const row of rows) {
    let exercise: Exercise;
    try {
      exercise = JSON.parse(row.payload) as Exercise;
    } catch {
      // A corrupt row is skipped rather than failing the search. The cache is
      // disposable by definition; the next online page replaces it.
      continue;
    }

    if (needle && !exercise.name.toLowerCase().includes(needle)) continue;
    if (filters.difficulty && exercise.difficulty !== filters.difficulty) continue;
    if (filters.equipment && !exercise.equipment.includes(filters.equipment)) continue;
    if (
      filters.muscleGroup &&
      !exercise.muscles.some((muscle) => muscle.groupSlug === filters.muscleGroup)
    ) {
      continue;
    }
    if (filters.favoritesOnly && !exercise.isFavorite) continue;

    matches.push(exercise);
    if (matches.length >= limit) break;
  }

  // Alphabetical, unlike the server's relevance ordering. Being honest about that is
  // better than pretending to reproduce a ranking this cannot see.
  return matches.sort((a, b) => a.name.localeCompare(b.name));
}

export async function cachedCount(): Promise<number> {
  const database = await openDatabase();
  const row = await database.getFirstAsync<{ count: number }>(
    "SELECT count(*) AS count FROM cached_exercises",
  );
  return row?.count ?? 0;
}
