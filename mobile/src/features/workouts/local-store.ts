/**
 * The active workout, in SQLite.
 *
 * Every read the workout screen performs comes from here, and every write lands here
 * before it touches the queue. That ordering is the product requirement: docs/08 opens
 * with basement gyms having no signal, so the network is something that happens
 * afterwards, not something the UI waits on.
 *
 * The whole session is stored as one JSON payload per row rather than normalised into
 * tables. A workout is read and written whole, always, and it is at most a few dozen
 * sets — normalising it would buy query flexibility nobody needs and cost a join on the
 * hottest path in the app.
 */

import { openDatabase, type SyncState } from "@/offline/database";

import type { LocalSession } from "./session-model";

// Re-exported so callers have one import for "the workout", model and storage alike.
export * from "./session-model";

type SessionRow = {
  id: string;
  payload: string;
  sync_state: SyncState;
  updated_at: number;
};

export type StoredSession = {
  session: LocalSession;
  syncState: SyncState;
  updatedAt: number;
};

function parse(row: SessionRow): StoredSession {
  return {
    session: JSON.parse(row.payload) as LocalSession,
    syncState: row.sync_state,
    updatedAt: row.updated_at,
  };
}

export async function saveSession(
  session: LocalSession,
  syncState: SyncState = "local",
): Promise<void> {
  const database = await openDatabase();
  await database.runAsync(
    `INSERT INTO local_sessions (id, payload, sync_state, updated_at)
     VALUES (?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       payload = excluded.payload,
       sync_state = excluded.sync_state,
       updated_at = excluded.updated_at`,
    session.id,
    JSON.stringify(session),
    syncState,
    Date.now(),
  );
}

export async function getSession(id: string): Promise<StoredSession | null> {
  const database = await openDatabase();
  const row = await database.getFirstAsync<SessionRow>(
    "SELECT * FROM local_sessions WHERE id = ?",
    id,
  );
  return row ? parse(row) : null;
}

/**
 * The workout the user is in the middle of, if any.
 *
 * This is what makes an interrupted session recoverable: the app is killed between
 * sets — a phone call, a low-memory kill, a battery death — and on relaunch the
 * workout is exactly where it was, because it was never anywhere else.
 */
export async function getActiveSession(): Promise<StoredSession | null> {
  const database = await openDatabase();
  const row = await database.getFirstAsync<SessionRow>(
    `SELECT * FROM local_sessions
     WHERE json_extract(payload, '$.completedAt') IS NULL
     ORDER BY updated_at DESC
     LIMIT 1`,
  );
  return row ? parse(row) : null;
}

export async function listRecentSessions(limit = 20): Promise<StoredSession[]> {
  const database = await openDatabase();
  const rows = await database.getAllAsync<SessionRow>(
    `SELECT * FROM local_sessions
     WHERE json_extract(payload, '$.completedAt') IS NOT NULL
     ORDER BY updated_at DESC
     LIMIT ?`,
    limit,
  );
  return rows.map(parse);
}

export async function deleteSession(id: string): Promise<void> {
  const database = await openDatabase();
  await database.runAsync("DELETE FROM local_sessions WHERE id = ?", id);
}
