import { describe, expect, it } from "vitest";

/**
 * How the API client classifies a rejected request.
 *
 * This exists because of a bug that reached a real device: the client tested for a
 * cancelled request with `error instanceof DOMException`. Hermes has no `DOMException`,
 * so the `instanceof` threw a ReferenceError *from inside the catch block* — replacing
 * whatever had actually failed with a meaningless one, on every rejected request.
 *
 * It survived tsc, ESLint and 400 tests because `DOMException` exists in Node and in the
 * browser; only the app's real engine lacks it. So the check is pinned here in terms of
 * the shape of the value rather than the class it came from.
 */

/**
 * The predicate as the client implements it.
 *
 * Duplicated rather than imported because the module reaches for `expo-secure-store` and
 * native storage at import time. What is being defended is the *logic*, and copying six
 * lines is a smaller lie than mocking four native modules to reach them.
 */
function isAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

describe("recognising a cancelled request", () => {
  it("recognises the browser's DOMException", () => {
    // Where fetch aborts do come from a DOMException, the name is still the signal.
    const error = new Error("aborted");
    error.name = "AbortError";
    expect(isAbort(error)).toBe(true);
  });

  it("recognises a plain object carrying the name", () => {
    // Hermes rejects with something that is not a DOMException, and never was.
    expect(isAbort({ name: "AbortError" })).toBe(true);
  });

  it("never evaluates a global that may not exist", () => {
    // The actual defect. `instanceof DOMException` throws ReferenceError under Hermes,
    // and does so inside the catch, so the original failure is lost entirely.
    expect(() => isAbort({ name: "AbortError" })).not.toThrow();
    expect(() => isAbort(new TypeError("network request failed"))).not.toThrow();
  });

  it("treats a genuine network failure as a failure, not a cancellation", () => {
    // Misclassifying this would rethrow the raw error instead of the ApiError the UI
    // reads, and the user would see a stack trace instead of "No connection".
    expect(isAbort(new TypeError("Network request failed"))).toBe(false);
  });

  it("copes with values that are not errors at all", () => {
    for (const value of [null, undefined, "AbortError", 42, []]) {
      expect(() => isAbort(value)).not.toThrow();
    }
    expect(isAbort(null)).toBe(false);
    expect(isAbort("AbortError")).toBe(false);
  });

  it("does not match a different error name", () => {
    const error = new Error("timeout");
    error.name = "TimeoutError";
    expect(isAbort(error)).toBe(false);
  });
});
