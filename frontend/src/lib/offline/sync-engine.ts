"use client";

import { api, ApiError } from "@/lib/api/client";
import { wal, type SyncOperation } from "@/lib/offline/wal";

/** The server caps a batch at 500 (`SyncRequest.operations`). */
const BATCH_SIZE = 500;

/**
 * Attempts before an operation is treated as poison.
 *
 * Without a ceiling, one malformed operation blocks the queue forever and every set
 * logged afterwards is stranded behind it. Dropping it loses one set; keeping it loses
 * all of them.
 */
const MAX_ATTEMPTS = 5;

export type SyncStatus = {
  pending: number;
  flushing: boolean;
  lastError: string | null;
  lastSyncedAt: number | null;
};

type Listener = (status: SyncStatus) => void;

type SyncResult = {
  opId: string;
  status: "applied" | "duplicate" | "rejected";
  reason: string | null;
};

let status: SyncStatus = { pending: 0, flushing: false, lastError: null, lastSyncedAt: null };
const listeners = new Set<Listener>();

function publish(next: Partial<SyncStatus>) {
  status = { ...status, ...next };
  for (const listener of listeners) listener(status);
}

export function subscribeToSync(listener: Listener): () => void {
  listeners.add(listener);
  listener(status);
  return () => listeners.delete(listener);
}

export function getSyncStatus(): SyncStatus {
  return status;
}

/**
 * Only one flush runs at a time.
 *
 * Two concurrent drains would read the same head of the log and send it twice. The
 * server would answer `duplicate` for the loser — correct, but it wastes a round trip
 * on a connection that is already struggling, which is the only time this code matters.
 */
let inFlight: Promise<void> | null = null;

export async function flush(): Promise<void> {
  if (inFlight) return inFlight;

  inFlight = (async () => {
    try {
      publish({ flushing: true, lastError: null });

      // Loops rather than sending one batch: a long offline session can hold far more
      // than the server's per-request cap.
      for (;;) {
        const batch = await wal.peek(BATCH_SIZE);
        if (batch.length === 0) break;

        const poisoned = batch.filter((op) => op.attempts >= MAX_ATTEMPTS);
        if (poisoned.length > 0) {
          await wal.remove(poisoned.map((op) => op.seq));
          continue;
        }

        let results: SyncResult[];
        try {
          const response = await api.post<{ results: SyncResult[]; serverTime: string }>(
            "/v1/workouts/sessions/sync",
            { operations: batch.map(toWireOperation) },
          );
          results = response.results;
        } catch (error) {
          // A 4xx means the batch will never be accepted as-is, so the attempt counter
          // moves it towards being dropped. Anything else — offline, 5xx — leaves the
          // log untouched to retry unchanged.
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
            await wal.recordAttempt(batch.map((op) => op.seq));
          }
          publish({
            flushing: false,
            lastError:
              error instanceof ApiError ? error.message : "Offline — changes are saved locally.",
            pending: await wal.count(),
          });
          return;
        }

        const settled = new Set(
          results
            .filter((r) => r.status === "applied" || r.status === "duplicate")
            .map((r) => r.opId),
        );

        // `duplicate` counts as settled: the server already has it, so keeping it
        // queued would replay it forever.
        const done = batch.filter((op) => settled.has(op.opId)).map((op) => op.seq);
        const refused = batch.filter((op) => !settled.has(op.opId));

        await wal.remove(done);
        if (refused.length > 0) {
          await wal.recordAttempt(refused.map((op) => op.seq));
        }

        // No progress and nothing settled means the head is stuck; stop rather than
        // spin, and let the attempt ceiling clear it on a later pass.
        if (done.length === 0) break;
      }

      publish({
        flushing: false,
        pending: await wal.count(),
        lastSyncedAt: Date.now(),
        lastError: null,
      });
    } finally {
      inFlight = null;
    }
  })();

  return inFlight;
}

function toWireOperation(operation: SyncOperation) {
  return {
    opId: operation.opId,
    type: operation.type,
    at: operation.at,
    payload: operation.payload,
  };
}

/** Records an operation and tries to send it. Never throws — the log is the promise. */
export async function enqueue(
  operation: Omit<SyncOperation, "seq" | "attempts">,
): Promise<void> {
  await wal.append(operation);
  publish({ pending: await wal.count() });
  void flush();
}

let started = false;

/**
 * Wires the triggers that drain the log.
 *
 * `online` is the important one: a phone that walked out of the gym's dead spot should
 * push its sets without the user reopening anything. Visibility covers the case where
 * the browser never fired `online` but the tab came back anyway, which is common on
 * mobile Safari.
 */
export function startSyncEngine(): () => void {
  if (started) return () => undefined;
  started = true;

  const onOnline = () => void flush();
  const onVisible = () => {
    if (document.visibilityState === "visible") void flush();
  };

  window.addEventListener("online", onOnline);
  document.addEventListener("visibilitychange", onVisible);

  void wal.count().then((pending) => publish({ pending }));
  void flush();

  return () => {
    window.removeEventListener("online", onOnline);
    document.removeEventListener("visibilitychange", onVisible);
    started = false;
  };
}
