import { describe, expect, it } from "vitest";

import { uuid7 } from "@/lib/utils/uuid7";

/**
 * The id is what makes offline replay safe: a set flushed twice carries the same
 * primary key, so the server's second insert is a no-op rather than a duplicate row
 * (docs/07 §3.3). These properties are the reason `crypto.randomUUID()` is not used.
 */
describe("uuid7", () => {
  const V7 = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

  it("emits the version 7 nibble and the RFC 4122 variant bits", () => {
    for (let i = 0; i < 200; i += 1) {
      expect(uuid7()).toMatch(V7);
    }
  });

  it("never repeats, even generated in a tight loop", () => {
    // A tight loop lands many ids inside one millisecond — the case a naive
    // timestamp-plus-random scheme collides on.
    const ids = Array.from({ length: 10_000 }, uuid7);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("sorts lexicographically in creation order", () => {
    // This is what the counter buys: without it, ids minted in the same millisecond
    // order randomly and lose the index locality the v7 layout exists for.
    const ids = Array.from({ length: 5_000 }, uuid7);
    expect(ids).toEqual([...ids].sort());
  });

  it("encodes the current time in the first 48 bits", () => {
    const before = Date.now();
    const timestamp = parseInt(uuid7().replace(/-/g, "").slice(0, 12), 16);
    const after = Date.now();

    expect(timestamp).toBeGreaterThanOrEqual(before);
    expect(timestamp).toBeLessThanOrEqual(after);
  });

  it("keeps ordering across a millisecond boundary", async () => {
    const first = uuid7();
    await new Promise((resolve) => setTimeout(resolve, 5));
    const second = uuid7();

    expect(second > first).toBe(true);
  });
});
