/**
 * Client-generated UUIDv7.
 *
 * Two properties matter, and `crypto.randomUUID()` (v4) has neither:
 *
 * **Time-ordered.** The first 48 bits are a millisecond timestamp, so ids sort by
 * creation. That keeps index locality on the server — random v4 keys scatter inserts
 * across a b-tree and fragment it.
 *
 * **Generated before the round trip.** The client mints the id, so a set logged
 * offline and flushed twice is one row rather than two: the server sees the same
 * primary key and the retry is a no-op. Reconciling an optimistic update becomes an
 * identity match instead of a guess (docs/07 §3.3).
 */

// Relies on a global `crypto.getRandomValues`. React Native has none by default, so
// `expo-crypto` is imported once in `app/_layout.tsx` — app-wide setup belongs at the
// entry point, and keeping this module free of native imports is what lets it be tested
// in plain Node.

let lastTimestamp = -1;
let sequence = 0;

export function uuid7(): string {
  const now = Date.now();

  // Several sets can be logged inside one millisecond — a superset finished in a
  // hurry, or a replayed offline queue. A per-millisecond counter keeps those
  // distinct *and* still ordered, which a fresh random draw would not.
  if (now === lastTimestamp) {
    sequence += 1;
  } else {
    lastTimestamp = now;
    sequence = 0;
  }

  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);

  // 48-bit big-endian timestamp.
  bytes[0] = (now / 2 ** 40) & 0xff;
  bytes[1] = (now / 2 ** 32) & 0xff;
  bytes[2] = (now / 2 ** 24) & 0xff;
  bytes[3] = (now / 2 ** 16) & 0xff;
  bytes[4] = (now / 2 ** 8) & 0xff;
  bytes[5] = now & 0xff;

  // Version 7 in the high nibble of byte 6, with the counter in the remaining
  // 12 bits of rand_a.
  bytes[6] = 0x70 | ((sequence >> 8) & 0x0f);
  bytes[7] = sequence & 0xff;

  // RFC 4122 variant bits.
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;

  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
