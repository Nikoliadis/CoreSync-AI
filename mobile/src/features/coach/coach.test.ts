import { describe, expect, it, vi } from "vitest";

/**
 * The SSE frame parser.
 *
 * This is the piece that only breaks in production. Short replies arrive in one chunk and
 * everything looks fine; a long one straddles two `onprogress` callbacks and a parser
 * that drops the partial tail loses a sentence out of the middle of the coach's answer,
 * silently, with no error anywhere.
 *
 * The `replace` frame carries real weight too. The output guard withholds the tail of a
 * reply and substitutes a safe one — if the client appends instead of replacing, the
 * unsafe fragment stays on screen followed by the correction.
 */

vi.mock("@/lib/api/client", () => ({
  API_BASE_URL: "http://test",
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  tokenStore: { get: () => "token" },
}));

const { parseFrames, remainingLabel } = await import("./api");

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

describe("parsing frames", () => {
  it("reads a complete frame", () => {
    const { events, rest } = parseFrames(frame("delta", { text: "Hello" }));

    expect(events).toEqual([{ type: "delta", text: "Hello" }]);
    expect(rest).toBe("");
  });

  it("reads several frames from one chunk", () => {
    const { events } = parseFrames(
      frame("delta", { text: "Hel" }) + frame("delta", { text: "lo" }),
    );

    expect(events.map((event) => (event.type === "delta" ? event.text : ""))).toEqual([
      "Hel",
      "lo",
    ]);
  });

  it("keeps a partial frame for the next chunk", () => {
    // The bug this exists for: a frame split across two onprogress callbacks. Dropping
    // the tail loses a sentence out of the middle of the answer, with no error.
    const whole = frame("delta", { text: "complete" });
    const split = whole.length - 6;

    const first = parseFrames(whole.slice(0, split));
    expect(first.events).toEqual([]);
    expect(first.rest).not.toBe("");

    const second = parseFrames(first.rest + whole.slice(split));
    expect(second.events).toEqual([{ type: "delta", text: "complete" }]);
  });

  it("reassembles a frame split mid-JSON", () => {
    const whole = frame("delta", { text: "a longer sentence than usual" });
    const first = parseFrames(whole.slice(0, 20));
    const second = parseFrames(first.rest + whole.slice(20));

    expect(second.events).toEqual([{ type: "delta", text: "a longer sentence than usual" }]);
  });

  it("surfaces replace as its own event, not as more text", () => {
    // Appending here would leave the withheld fragment on screen with the safe answer
    // after it, which is the exact outcome the guard exists to prevent.
    const { events } = parseFrames(frame("replace", { text: "Safe answer." }));

    expect(events).toEqual([{ type: "replace", text: "Safe answer." }]);
  });

  it("reads the closing message frame", () => {
    const { events } = parseFrames(
      frame("message", {
        conversationId: "conv-1",
        message: { id: "m1", role: "assistant", content: "Done." },
        toolsUsed: ["get_recent_workouts"],
      }),
    );

    expect(events[0]).toMatchObject({
      type: "message",
      conversationId: "conv-1",
      toolsUsed: ["get_recent_workouts"],
    });
  });

  it("reads an error frame that arrives after the status line", () => {
    const { events } = parseFrames(frame("error", { message: "Upstream failed." }));
    expect(events).toEqual([{ type: "error", message: "Upstream failed." }]);
  });

  it("falls back to a usable message when an error frame carries none", () => {
    const { events } = parseFrames(frame("error", {}));
    expect(events).toEqual([{ type: "error", message: "Something went wrong." }]);
  });

  it("never renders an object as [object Object]", () => {
    // String(someObject) would put that literal text into the reply as if the coach had
    // said it.
    const { events } = parseFrames(frame("delta", { text: { nested: true } }));
    expect(events).toEqual([{ type: "delta", text: "" }]);
  });

  it("drops non-string entries from a tools list", () => {
    const { events } = parseFrames(frame("tools", { tools: ["ok", 42, null] }));
    expect(events).toEqual([{ type: "tools", tools: ["ok"] }]);
  });

  it("skips a malformed frame rather than failing the whole answer", () => {
    const { events } = parseFrames(
      `event: delta\ndata: {not json\n\n${frame("delta", { text: "survived" })}`,
    );

    expect(events).toEqual([{ type: "delta", text: "survived" }]);
  });

  it("ignores a frame with no data line", () => {
    const { events } = parseFrames("event: ping\n\n");
    expect(events).toEqual([]);
  });

  it("ignores an event type it does not know", () => {
    // Forward compatibility: the server may add frames before this client ships.
    const { events } = parseFrames(frame("heartbeat", { at: 1 }));
    expect(events).toEqual([]);
  });

  it("handles an empty buffer", () => {
    expect(parseFrames("")).toEqual({ events: [], rest: "" });
  });
});

describe("the daily allowance", () => {
  function usage(overrides: Partial<import("./api").Usage> = {}) {
    return {
      messagesUsed: 2,
      messagesLimit: 10,
      messagesRemaining: 8,
      tokensUsed: 500,
      ...overrides,
    };
  }

  it("says how many are left", () => {
    expect(remainingLabel(usage())).toBe("8 left today");
  });

  it("says plainly when there are none", () => {
    expect(remainingLabel(usage({ messagesRemaining: 0 }))).toBe("No messages left today");
  });

  it("says nothing when there is no limit to report", () => {
    // An unlimited plan should not display "0 left today".
    expect(remainingLabel(usage({ messagesLimit: 0 }))).toBeNull();
    expect(remainingLabel(undefined)).toBeNull();
  });
});
