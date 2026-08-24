/**
 * The local database. Everything the UI reads comes from here, online or not.
 *
 * That is the whole design, and it is not a caching strategy — it is the product
 * requirement. docs/08 opens with the constraint that drives it: basement gyms have no
 * signal, and **every write works offline, no exceptions**. A UI that reads from the
 * network is a UI that shows a spinner in the one place it must not.
 *
 * Schema follows docs/08 §4.1 exactly. Two things worth knowing about it:
 *
 * * Rows carry a `sync_state`, so the UI can show "saved locally" without guessing.
 * * `operation_queue` is append-only and ordered, and its primary key is the same
 *   UUIDv7 the server will see as an idempotency key. That is what makes a replayed
 *   flush one row instead of two.
 */

import * as SQLite from "expo-sqlite";

const DATABASE_NAME = "coresync.db";

export type SyncState = "local" | "syncing" | "synced" | "conflict";

/** Bumped whenever a migration is added below. */
export const SCHEMA_VERSION = 1;

const MIGRATIONS: readonly string[] = [
  // v1 — the shape docs/08 §4.1 specifies.
  `
  CREATE TABLE IF NOT EXISTS local_sessions (
      id TEXT PRIMARY KEY,
      payload TEXT NOT NULL,
      sync_state TEXT NOT NULL
          CHECK (sync_state IN ('local','syncing','synced','conflict')),
      updated_at INTEGER NOT NULL
  );

  CREATE TABLE IF NOT EXISTS local_sets (
      id TEXT PRIMARY KEY,
      session_id TEXT,
      payload TEXT NOT NULL,
      sync_state TEXT NOT NULL
          CHECK (sync_state IN ('local','syncing','synced','conflict')),
      updated_at INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS ix_local_sets_session ON local_sets (session_id);

  CREATE TABLE IF NOT EXISTS local_diary (
      id TEXT PRIMARY KEY,
      local_date TEXT NOT NULL,
      payload TEXT NOT NULL,
      sync_state TEXT NOT NULL
          CHECK (sync_state IN ('local','syncing','synced','conflict')),
      updated_at INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS ix_local_diary_date ON local_diary (local_date);

  -- The write-ahead log. Append-only, ordered, drained by the sync engine.
  CREATE TABLE IF NOT EXISTS operation_queue (
      op_id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0,
      last_error TEXT,
      next_attempt_at INTEGER NOT NULL DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS ix_queue_ready
      ON operation_queue (next_attempt_at, created_at);

  -- Reference data, cached so the exercise picker and food search work with no signal.
  CREATE TABLE IF NOT EXISTS cached_exercises (
      id TEXT PRIMARY KEY, payload TEXT NOT NULL, cached_at INTEGER NOT NULL
  );
  CREATE TABLE IF NOT EXISTS cached_foods (
      id TEXT PRIMARY KEY, payload TEXT NOT NULL, cached_at INTEGER NOT NULL
  );
  `,
];

let handle: SQLite.SQLiteDatabase | null = null;

export async function openDatabase(): Promise<SQLite.SQLiteDatabase> {
  if (handle) return handle;

  const database = await SQLite.openDatabaseAsync(DATABASE_NAME);

  // WAL, because the sync engine writes while the UI reads. Without it a flush blocks
  // the screen the user is looking at, which on this product means it blocks logging
  // a set.
  await database.execAsync("PRAGMA journal_mode = WAL;");
  await database.execAsync("PRAGMA foreign_keys = ON;");

  const row = await database.getFirstAsync<{ user_version: number }>(
    "PRAGMA user_version",
  );
  const current = row?.user_version ?? 0;

  for (let version = current; version < MIGRATIONS.length; version += 1) {
    const migration = MIGRATIONS[version];
    if (migration) await database.execAsync(migration);
  }
  if (current < MIGRATIONS.length) {
    // Interpolated because PRAGMA does not accept a bound parameter. The value is a
    // loop counter over a module-level array, never anything a caller supplies.
    await database.execAsync(`PRAGMA user_version = ${MIGRATIONS.length}`);
  }

  handle = database;
  return database;
}

/** Test and logout helper: drop the handle so the next open re-reads from disk. */
export async function closeDatabase(): Promise<void> {
  if (!handle) return;
  await handle.closeAsync();
  handle = null;
}

/**
 * Wipe local state on logout.
 *
 * Reference caches survive: they are not personal, and re-downloading two hundred
 * exercises on the next login is a slow first screen for no benefit.
 */
export async function clearUserData(): Promise<void> {
  const database = await openDatabase();
  await database.execAsync(`
    DELETE FROM operation_queue;
    DELETE FROM local_sets;
    DELETE FROM local_sessions;
    DELETE FROM local_diary;
  `);
}
