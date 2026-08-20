/**
 * The client's write-ahead log.
 *
 * Every workout mutation is written here **before** it is sent. The server drains it
 * through `/workouts/sessions/sync`, applying operations in client order and keyed on
 * `opId`, so replaying a batch is always safe (docs/04 §5).
 *
 * IndexedDB rather than localStorage, for two reasons that both bite mid-workout:
 * localStorage is synchronous and blocks the main thread on every write, and its ~5 MB
 * string budget is shared with everything else the origin stores. A lifter logging sets
 * on a phone should never wait on storage.
 */

export type SyncOperationType =
  | "session.create"
  | "session.update"
  | "session.complete"
  | "session.discard"
  | "exercise.add"
  | "set.log"
  | "set.update"
  | "set.delete";

export type SyncOperation = {
  /** Idempotency unit. The server treats a repeat as `duplicate`, never a second write. */
  opId: string;
  type: SyncOperationType;
  /** When the user performed it, not when it was sent. */
  at: string;
  payload: Record<string, unknown>;
  /** Monotonic within this client, so ordering survives equal timestamps. */
  seq: number;
  attempts: number;
};

const DB_NAME = "coresync-offline";
const DB_VERSION = 1;
const STORE = "wal";

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  dbPromise ??= new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        // Keyed by `seq` so a cursor walk returns operations in the order the user
        // performed them. Order is the whole point: a set logged against an exercise
        // that has not been added yet is rejected.
        const store = db.createObjectStore(STORE, { keyPath: "seq" });
        store.createIndex("opId", "opId", { unique: true });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

  return dbPromise;
}

function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const transaction = db.transaction(STORE, mode);
        const request = run(transaction.objectStore(STORE));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      }),
  );
}

/**
 * Sequence numbers survive reloads by starting from whatever is already stored.
 *
 * Resetting to zero on every load would make a replayed batch interleave with new
 * work in the wrong order, which is exactly the corruption the log exists to prevent.
 */
let nextSeq: number | null = null;

async function claimSeq(): Promise<number> {
  if (nextSeq === null) {
    const keys = await tx<IDBValidKey[]>("readonly", (store) => store.getAllKeys());
    const highest = keys.length ? Math.max(...keys.map(Number)) : 0;
    nextSeq = highest + 1;
  }
  const seq = nextSeq;
  nextSeq += 1;
  return seq;
}

export const wal = {
  /** Records an operation. Returns once it is durable. */
  async append(
    operation: Omit<SyncOperation, "seq" | "attempts">,
  ): Promise<SyncOperation> {
    const entry: SyncOperation = { ...operation, seq: await claimSeq(), attempts: 0 };
    await tx("readwrite", (store) => store.add(entry));
    return entry;
  },

  /** The oldest `limit` operations, in the order the user performed them. */
  async peek(limit: number): Promise<SyncOperation[]> {
    const all = await tx<SyncOperation[]>("readonly", (store) => store.getAll());
    return all.sort((a, b) => a.seq - b.seq).slice(0, limit);
  },

  async remove(seqs: number[]): Promise<void> {
    if (seqs.length === 0) return;
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(STORE, "readwrite");
      const store = transaction.objectStore(STORE);
      for (const seq of seqs) store.delete(seq);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
  },

  /** Bumps the attempt counter so a poisoned operation can be identified. */
  async recordAttempt(seqs: number[]): Promise<void> {
    if (seqs.length === 0) return;
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(STORE, "readwrite");
      const store = transaction.objectStore(STORE);
      for (const seq of seqs) {
        const get = store.get(seq);
        get.onsuccess = () => {
          const entry = get.result as SyncOperation | undefined;
          if (entry) store.put({ ...entry, attempts: entry.attempts + 1 });
        };
      }
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
  },

  async count(): Promise<number> {
    return tx<number>("readonly", (store) => store.count());
  },

  /** Test and sign-out helper — clears everything pending. */
  async clear(): Promise<void> {
    await tx("readwrite", (store) => store.clear());
    nextSeq = null;
  },
};
