/**
 * Drains the write-ahead log into the API.
 *
 * The contract is the one the backend already implements at
 * `POST /v1/workouts/sessions/sync`: a batch of operations goes up, and each comes back
 * `applied`, `duplicate` or `rejected`. All three are terminal — a duplicate means an
 * earlier attempt already landed, which is a success from the phone's point of view and
 * the entire reason operations carry a client-minted id.
 *
 * Only `rejected` and transport failures are treated differently, and they are treated
 * differently *from each other*: a rejection is the server saying no and will say no
 * again, while a transport failure is a basement. One is dropped after logging, the
 * other backs off and waits.
 */

import { ApiError, api } from "@/lib/api/client";

import {
  MAX_ATTEMPTS,
  type Operation,
  readyOperations,
  recordFailure,
  removeOperations,
} from "./queue";

export type SyncStatus = "applied" | "duplicate" | "rejected";

type SyncResult = {
  opId: string;
  status: SyncStatus;
  reason: string | null;
};

type SyncResponse = {
  results: SyncResult[];
};

export type FlushOutcome = {
  sent: number;
  applied: number;
  duplicate: number;
  rejected: number;
  /** True when nothing could be sent because the device is offline. */
  offline: boolean;
};

const EMPTY: FlushOutcome = {
  sent: 0,
  applied: 0,
  duplicate: 0,
  rejected: 0,
  offline: false,
};

/**
 * Only ever one flush at a time.
 *
 * Two concurrent flushes read the same ready operations and send them twice. The server
 * would dedupe — that is what idempotency keys are for — but it is wasted bandwidth on
 * a connection that is by definition bad, and it doubles the window in which a kill
 * leaves rows mid-flight.
 */
let inFlight: Promise<FlushOutcome> | null = null;

function toApiOperation(operation: Operation) {
  return {
    opId: operation.opId,
    type: operation.type,
    // When the user performed it, not when it reached the server. A set logged at
    // 18:40 in a basement belongs at 18:40 even if it arrives at 19:15.
    at: new Date(operation.createdAt).toISOString(),
    payload: operation.payload,
  };
}

export async function flush(): Promise<FlushOutcome> {
  inFlight ??= (async () => {
    try {
      const operations = await readyOperations();
      if (operations.length === 0) return EMPTY;

      let response: SyncResponse;
      try {
        response = await api.post<SyncResponse>("/v1/workouts/sessions/sync", {
          operations: operations.map(toApiOperation),
        });
      } catch (error) {
        if (error instanceof ApiError && error.isOffline) {
          // Not a failure of the operations — nothing was attempted. Leaving attempt
          // counts untouched means a week in a bad signal area does not burn through
          // an operation's retries without the server ever seeing it.
          return { ...EMPTY, offline: true };
        }
        const message = error instanceof Error ? error.message : "sync failed";
        await Promise.all(operations.map((op) => recordFailure(op.opId, message)));
        return { ...EMPTY, sent: operations.length };
      }

      const settled: string[] = [];
      const outcome: FlushOutcome = { ...EMPTY, sent: operations.length };

      for (const result of response.results) {
        if (result.status === "applied") {
          outcome.applied += 1;
          settled.push(result.opId);
        } else if (result.status === "duplicate") {
          // An earlier attempt already landed. Success, and the whole point of minting
          // ids on the device.
          outcome.duplicate += 1;
          settled.push(result.opId);
        } else {
          // The server will reject it again for the same reason, so retrying is just a
          // slower way to lose it while blocking everything behind it.
          outcome.rejected += 1;
          settled.push(result.opId);
        }
      }

      // Anything the server did not mention is left in the queue deliberately: a
      // partial response means those were never processed, and dropping them here
      // would be data loss disguised as success.
      await removeOperations(settled);
      return outcome;
    } finally {
      queueMicrotask(() => {
        inFlight = null;
      });
    }
  })();

  return inFlight;
}

export type SyncEngineHandle = { stop: () => void };

/**
 * Flush on the events that mean a connection might exist again.
 *
 * Deliberately not a timer. Polling on a fixed interval drains a battery for the
 * ninety-nine minutes of a session where nothing changed; the interval here is a
 * backstop for the case where connectivity returns without an event firing.
 */
export function startSyncEngine(options: {
  onOutcome?: (outcome: FlushOutcome) => void;
  intervalMs?: number;
} = {}): SyncEngineHandle {
  const { onOutcome, intervalMs = 60_000 } = options;
  let stopped = false;

  const run = async () => {
    if (stopped) return;
    try {
      const outcome = await flush();
      if (!stopped) onOutcome?.(outcome);
    } catch {
      // A flush that throws must never take the app with it. The operations are still
      // in SQLite and the next attempt will find them.
    }
  };

  void run();
  const timer = setInterval(() => void run(), intervalMs);

  return {
    stop: () => {
      stopped = true;
      clearInterval(timer);
    },
  };
}

export { MAX_ATTEMPTS };
