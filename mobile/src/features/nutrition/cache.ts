import { openDatabase } from "@/offline/database";

import type { Diary } from "./api";

/**
 * A read-through cache of the diary, one row per day.
 *
 * Reads only. Nutrition writes are not cached and not queued, because
 * `POST /v1/nutrition/diary` mints the entry id server-side and there is no nutrition
 * sync endpoint — a replayed write would create a second entry rather than reconcile
 * with the first. Queuing something the server cannot deduplicate would turn a bad
 * connection into duplicated food, which is worse than refusing to log.
 *
 * So this exists to answer "what did I eat today" with no signal, and nothing more.
 * `local_diary` has been in the schema since the first migration.
 */
type CachedRow = { id: string; local_date: string; payload: string; updated_at: number };

/** The cache key. One row per day, replaced whole whenever the server answers. */
const DIARY_ID = (localDate: string) => `diary:${localDate}`;

export async function cacheDiary(diary: Diary): Promise<void> {
  const database = await openDatabase();
  await database.runAsync(
    `INSERT INTO local_diary (id, local_date, payload, sync_state, updated_at)
     VALUES (?, ?, ?, 'synced', ?)
     ON CONFLICT(id) DO UPDATE SET
       payload = excluded.payload,
       sync_state = excluded.sync_state,
       updated_at = excluded.updated_at`,
    DIARY_ID(diary.localDate),
    diary.localDate,
    JSON.stringify(diary),
    Date.now(),
  );
}

export async function cachedDiary(localDate: string): Promise<Diary | null> {
  const database = await openDatabase();
  const row = await database.getFirstAsync<CachedRow>(
    "SELECT * FROM local_diary WHERE id = ?",
    DIARY_ID(localDate),
  );
  if (!row) return null;
  try {
    return JSON.parse(row.payload) as Diary;
  } catch {
    // A corrupt row is a cache miss, not a crash. The next online read replaces it.
    return null;
  }
}

/** Dropped on logout along with the rest of the user's local state. */
export async function clearDiaryCache(): Promise<void> {
  const database = await openDatabase();
  await database.runAsync("DELETE FROM local_diary");
}
