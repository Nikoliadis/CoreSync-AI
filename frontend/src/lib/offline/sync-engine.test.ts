import "fake-indexeddb/auto";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { wal, type SyncOperationType } from "@/lib/offline/wal";

const post = vi.fn();

vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client");
  return { ...actual, api: { ...actual.api, post: (...args: unknown[]) => post(...args) } };
});

const { enqueue, flush, getSyncStatus } = await import("@/lib/offline/sync-engine");

type Result = { opId: string; status: "applied" | "duplicate" | "rejected"; reason: string | null };

function applyAll(results: Result["status"] = "applied") {
  post.mockImplementation((_path: string, body: { operations: { opId: string }[] }) => ({
    results: body.operations.map((o) => ({ opId: o.opId, status: results, reason: null })),
    serverTime: new Date().toISOString(),
  }));
}

function op(opId: string, type: SyncOperationType = "set.log") {
  return { opId, type, at: new Date().toISOString(), payload: {} };
}

describe("sync engine", () => {
  beforeEach(async () => {
    post.mockReset();
    await wal.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("drains applied operations from the log", async () => {
    applyAll("applied");

    await enqueue(op("a"));
    await enqueue(op("b"));
    await flush();

    expect(await wal.count()).toBe(0);
  });

  it("sends operations in the order they were performed", async () => {
    applyAll();

    // Appended directly rather than through `enqueue`, which flushes eagerly — this is
    // the shape of a queue that built up while the phone had no signal.
    await wal.append(op("first"));
    await wal.append(op("second"));
    await wal.append(op("third"));
    await flush();

    const sent = post.mock.calls.at(-1)?.[1] as { operations: { opId: string }[] };
    expect(sent.operations.map((o) => o.opId)).toEqual(["first", "second", "third"]);
  });

  it("treats a duplicate as settled", async () => {
    // The server already has it. Keeping it queued would replay it forever.
    applyAll("duplicate");

    await enqueue(op("a"));
    await flush();

    expect(await wal.count()).toBe(0);
  });

  it("keeps everything when the network is down", async () => {
    // The whole point: an offline set is not lost, it waits.
    post.mockRejectedValue(new TypeError("Failed to fetch"));

    await enqueue(op("a"));
    await enqueue(op("b"));
    await flush();

    expect(await wal.count()).toBe(2);
    expect(getSyncStatus().lastError).toBeTruthy();
  });

  it("retries the same operations unchanged after an outage", async () => {
    post.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await enqueue(op("a"));
    await flush();
    expect(await wal.count()).toBe(1);

    applyAll();
    await flush();
    expect(await wal.count()).toBe(0);
  });

  it("keeps a rejected operation but counts the attempt", async () => {
    post.mockImplementation((_path: string, body: { operations: { opId: string }[] }) => ({
      results: body.operations.map((o) => ({
        opId: o.opId,
        status: "rejected",
        reason: "unknown session",
      })),
      serverTime: new Date().toISOString(),
    }));

    await enqueue(op("bad"));
    await flush();

    const [entry] = await wal.peek(1);
    expect(entry.attempts).toBeGreaterThan(0);
  });

  it("eventually drops a poisoned operation rather than blocking the queue", async () => {
    // One malformed operation must not strand every set logged after it. Dropping it
    // loses one set; keeping it loses all of them.
    post.mockImplementation((_path: string, body: { operations: { opId: string }[] }) => ({
      results: body.operations.map((o) => ({
        opId: o.opId,
        status: "rejected",
        reason: "malformed",
      })),
      serverTime: new Date().toISOString(),
    }));

    await enqueue(op("poison"));
    for (let i = 0; i < 8; i += 1) await flush();

    expect(await wal.count()).toBe(0);
  });

  it("counts a 4xx against the attempt ceiling", async () => {
    post.mockRejectedValue(new ApiError(400, "validation_error", "nope"));

    await enqueue(op("a"));
    await flush();

    const [entry] = await wal.peek(1);
    expect(entry.attempts).toBe(1);
  });

  it("does not count a 5xx against it", async () => {
    // A server having a bad minute is not the client's operation being wrong.
    post.mockRejectedValue(new ApiError(503, "upstream_unavailable", "down"));

    await enqueue(op("a"));
    await flush();

    const [entry] = await wal.peek(1);
    expect(entry.attempts).toBe(0);
  });

  it("never runs two flushes at once", async () => {
    // Two concurrent drains would read the same head and send it twice.
    post.mockImplementation(
      async (_path: string, body: { operations: { opId: string }[] }) => {
        await new Promise((resolve) => setTimeout(resolve, 20));
        return {
          results: body.operations.map((o) => ({
            opId: o.opId,
            status: "applied",
            reason: null,
          })),
          serverTime: new Date().toISOString(),
        };
      },
    );

    await wal.append(op("a"));
    await Promise.all([flush(), flush()]);

    expect(post).toHaveBeenCalledTimes(1);
  });

  it("reports pending work through its status", async () => {
    post.mockRejectedValue(new TypeError("offline"));

    await enqueue(op("a"));
    await flush();

    expect(getSyncStatus().pending).toBe(1);
    expect(getSyncStatus().flushing).toBe(false);
  });

  it("clears the error and stamps the time on success", async () => {
    applyAll();

    await enqueue(op("a"));
    await flush();

    expect(getSyncStatus().lastError).toBeNull();
    expect(getSyncStatus().lastSyncedAt).toBeTypeOf("number");
  });
});
