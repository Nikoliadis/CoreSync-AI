import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it } from "vitest";

import { wal, type SyncOperationType } from "@/lib/offline/wal";

function op(opId: string, type: SyncOperationType = "set.log") {
  return { opId, type, at: new Date().toISOString(), payload: { reps: 5 } };
}

/**
 * The write-ahead log is where offline data loss would happen, and docs/15 lists that
 * as a *fatal* risk. Ordering and durability are asserted directly rather than assumed
 * from the shape of the code.
 */
describe("wal", () => {
  beforeEach(async () => {
    await wal.clear();
  });

  it("starts empty", async () => {
    expect(await wal.count()).toBe(0);
    expect(await wal.peek(10)).toEqual([]);
  });

  it("returns operations in the order they were performed", async () => {
    // Order is the whole point: a set logged against an exercise that has not been
    // added yet is rejected by the server.
    await wal.append(op("a"));
    await wal.append(op("b"));
    await wal.append(op("c"));

    expect((await wal.peek(10)).map((o) => o.opId)).toEqual(["a", "b", "c"]);
  });

  it("assigns increasing sequence numbers", async () => {
    await wal.append(op("a"));
    await wal.append(op("b"));

    const [first, second] = await wal.peek(10);
    expect(second.seq).toBeGreaterThan(first.seq);
  });

  it("survives operations sharing a timestamp", async () => {
    // Several sets inside one millisecond is ordinary during a superset. A timestamp
    // alone cannot order them; the sequence number can.
    const at = new Date().toISOString();
    for (const id of ["a", "b", "c"]) {
      await wal.append({ opId: id, type: "set.log", at, payload: {} });
    }

    expect((await wal.peek(10)).map((o) => o.opId)).toEqual(["a", "b", "c"]);
  });

  it("honours the peek limit", async () => {
    for (const id of ["a", "b", "c", "d"]) await wal.append(op(id));
    expect(await wal.peek(2)).toHaveLength(2);
  });

  it("removes only what it is told to", async () => {
    const first = await wal.append(op("a"));
    await wal.append(op("b"));

    await wal.remove([first.seq]);

    expect((await wal.peek(10)).map((o) => o.opId)).toEqual(["b"]);
  });

  it("tolerates removing something already gone", async () => {
    // The flusher can race with itself on a slow connection; a double delete must not
    // throw and strand the rest of the queue.
    const entry = await wal.append(op("a"));
    await wal.remove([entry.seq]);
    await expect(wal.remove([entry.seq])).resolves.toBeUndefined();
  });

  it("counts what is pending", async () => {
    await wal.append(op("a"));
    await wal.append(op("b"));
    expect(await wal.count()).toBe(2);
  });

  it("tracks attempts so a poisoned operation can be identified", async () => {
    const entry = await wal.append(op("a"));

    await wal.recordAttempt([entry.seq]);
    await wal.recordAttempt([entry.seq]);

    expect((await wal.peek(1))[0].attempts).toBe(2);
  });

  it("keeps the payload intact through a round trip", async () => {
    await wal.append({
      opId: "a",
      type: "set.log",
      at: "2026-08-01T10:00:00.000Z",
      payload: { reps: 8, weightKg: 102.5, nested: { rpe: 9 } },
    });

    const [stored] = await wal.peek(1);
    expect(stored.payload).toEqual({ reps: 8, weightKg: 102.5, nested: { rpe: 9 } });
    expect(stored.at).toBe("2026-08-01T10:00:00.000Z");
  });

  it("rejects a duplicate opId", async () => {
    // The opId is the server's idempotency unit. Two different operations sharing one
    // would make a replay silently drop the second.
    await wal.append(op("same"));
    await expect(wal.append(op("same"))).rejects.toBeTruthy();
  });

  it("clears everything", async () => {
    await wal.append(op("a"));
    await wal.clear();
    expect(await wal.count()).toBe(0);
  });
});
