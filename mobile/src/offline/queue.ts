/**
 * The write-ahead log.
 *
 * Every write the app makes is appended here first and applied to local state second,
 * so the UI updates immediately and the network becomes something that happens later.
 * The queue is the source of truth for "what have I not told the server yet" — losing
 * it loses data, which is why it lives in SQLite rather than memory.
 *
 * `op_id` is a client-minted UUIDv7 and doubles as the idempotency key the server
 * dedupes on. That is what makes a flush safe to replay: a kill mid-flush leaves
 * operations that were already applied, and re-sending them is a no-op rather than a
 * duplicate set.
 */

import { openDatabase } from "./database";
import { uuid7 } from "@/lib/utils/uuid7";

/**
 * Exactly the operations `SyncWorkoutsUseCase._HANDLERS` dispatches on.
 *
 * Kept in lockstep deliberately: the server answers an unknown type with `rejected`,
 * and a rejection is terminal here — so a typo in this union is silent data loss rather
 * than an error anybody sees. Nutrition and water are absent because the sync endpoint
 * does not handle them; those go through their own online endpoints.
 */
export type OperationType =
  | "session.create"
  | "session.update"
  | "exercise.add"
  | "set.log"
  | "set.update"
  | "set.delete"
  | "session.complete"
  | "session.discard";

export type Operation = {
  opId: string;
  type: OperationType;
  payload: unknown;
  createdAt: number;
  attempts: number;
  lastError: string | null;
  nextAttemptAt: number;
};

type QueueRow = {
  op_id: string;
  type: string;
  payload: string;
  created_at: number;
  attempts: number;
  last_error: string | null;
  next_attempt_at: number;
};

/**
 * Give up after this many tries.
 *
 * An operation that has failed five times is not failing because of the network — it is
 * being rejected. Retrying it forever would block everything queued behind it, which is
 * the one thing worse than losing it.
 */
export const MAX_ATTEMPTS = 5;

/** How many go up in one request. Matches the server's sync batch limit. */
export const BATCH_SIZE = 500;

function toOperation(row: QueueRow): Operation {
  return {
    opId: row.op_id,
    type: row.type as OperationType,
    payload: JSON.parse(row.payload),
    createdAt: row.created_at,
    attempts: row.attempts,
    lastError: row.last_error,
    nextAttemptAt: row.next_attempt_at,
  };
}

export async function enqueue(type: OperationType, payload: unknown): Promise<string> {
  const database = await openDatabase();
  const opId = uuid7();
  await database.runAsync(
    `INSERT INTO operation_queue (op_id, type, payload, created_at, next_attempt_at)
     VALUES (?, ?, ?, ?, 0)`,
    opId,
    type,
    JSON.stringify(payload),
    Date.now(),
  );
  return opId;
}

/**
 * The operations due for sending, oldest first.
 *
 * Order matters and is not incidental: `session.start` has to reach the server before
 * the sets that belong to it, and `created_at` ordering is what guarantees that without
 * the queue needing to understand the relationship.
 */
export async function readyOperations(limit = BATCH_SIZE): Promise<Operation[]> {
  const database = await openDatabase();
  const rows = await database.getAllAsync<QueueRow>(
    `SELECT * FROM operation_queue
     WHERE next_attempt_at <= ? AND attempts < ?
     ORDER BY created_at ASC
     LIMIT ?`,
    Date.now(),
    MAX_ATTEMPTS,
    limit,
  );
  return rows.map(toOperation);
}

export async function removeOperations(opIds: readonly string[]): Promise<void> {
  if (opIds.length === 0) return;
  const database = await openDatabase();
  const placeholders = opIds.map(() => "?").join(",");
  await database.runAsync(
    `DELETE FROM operation_queue WHERE op_id IN (${placeholders})`,
    ...opIds,
  );
}

/**
 * Record a failure and push the retry out.
 *
 * Exponential with a ceiling: a phone that has been in a basement for an hour should
 * not be attempting every two seconds, and a server having a bad minute should not be
 * hammered by every client at once.
 */
export async function recordFailure(opId: string, error: string): Promise<void> {
  const database = await openDatabase();
  const row = await database.getFirstAsync<{ attempts: number }>(
    "SELECT attempts FROM operation_queue WHERE op_id = ?",
    opId,
  );
  const attempts = (row?.attempts ?? 0) + 1;
  const backoffMs = Math.min(2 ** attempts * 1000, 5 * 60_000);

  await database.runAsync(
    `UPDATE operation_queue
     SET attempts = ?, last_error = ?, next_attempt_at = ?
     WHERE op_id = ?`,
    attempts,
    error.slice(0, 500),
    Date.now() + backoffMs,
    opId,
  );
}

export async function pendingCount(): Promise<number> {
  const database = await openDatabase();
  const row = await database.getFirstAsync<{ count: number }>(
    "SELECT count(*) AS count FROM operation_queue",
  );
  return row?.count ?? 0;
}

/**
 * Operations that have exhausted their retries.
 *
 * Surfaced rather than silently dropped: the user logged this and it never arrived, and
 * they are entitled to know which one rather than discovering a hole in their history
 * three weeks later.
 */
export async function deadLetters(): Promise<Operation[]> {
  const database = await openDatabase();
  const rows = await database.getAllAsync<QueueRow>(
    `SELECT * FROM operation_queue WHERE attempts >= ? ORDER BY created_at ASC`,
    MAX_ATTEMPTS,
  );
  return rows.map(toOperation);
}
