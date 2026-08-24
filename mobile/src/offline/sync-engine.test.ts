import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The sync engine, tested against a stubbed queue and API.
 *
 * These assertions are about data loss, which is the only failure mode here that
 * matters. An operation dropped because the server rejected it is a decision; an
 * operation dropped because the phone went into a lift is a bug, and the two look
 * identical from inside a `catch`.
 */

const queue = vi.hoisted(() => ({
  readyOperations: vi.fn(),
  removeOperations: vi.fn(),
  recordFailure: vi.fn(),
  MAX_ATTEMPTS: 5,
  BATCH_SIZE: 500,
}));

const client = vi.hoisted(() => {
  class ApiError extends Error {
    status: number;
    code: string;
    details: unknown[] = [];
    constructor(status: number, code: string, message: string) {
      super(message);
      this.status = status;
      this.code = code;
    }
    get isOffline() {
      return this.status === 0;
    }
  }
  return { api: { post: vi.fn() }, ApiError };
});

vi.mock("./queue", () => queue);
vi.mock("@/lib/api/client", () => client);

const { flush } = await import("./sync-engine");

function operation(opId: string, type = "set.log") {
  return {
    opId,
    type,
    payload: { reps: 8 },
    createdAt: 1_700_000_000_000,
    attempts: 0,
    lastError: null,
    nextAttemptAt: 0,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  queue.removeOperations.mockResolvedValue(undefined);
  queue.recordFailure.mockResolvedValue(undefined);
});

describe("an empty queue", () => {
  it("sends nothing", async () => {
    queue.readyOperations.mockResolvedValue([]);
    const outcome = await flush();

    expect(client.api.post).not.toHaveBeenCalled();
    expect(outcome.sent).toBe(0);
  });
});

describe("a successful flush", () => {
  it("clears applied operations", async () => {
    queue.readyOperations.mockResolvedValue([operation("a"), operation("b")]);
    client.api.post.mockResolvedValue({
      results: [
        { opId: "a", status: "applied", reason: null },
        { opId: "b", status: "applied", reason: null },
      ],
    });

    const outcome = await flush();

    expect(outcome.applied).toBe(2);
    expect(queue.removeOperations).toHaveBeenCalledWith(["a", "b"]);
  });

  it("treats a duplicate as success", async () => {
    // The whole reason operations carry a client-minted id: an earlier attempt landed,
    // the retry is a no-op, and the phone should stop asking.
    queue.readyOperations.mockResolvedValue([operation("a")]);
    client.api.post.mockResolvedValue({
      results: [{ opId: "a", status: "duplicate", reason: "already applied" }],
    });

    const outcome = await flush();

    expect(outcome.duplicate).toBe(1);
    expect(queue.removeOperations).toHaveBeenCalledWith(["a"]);
  });

  it("drops a rejection rather than retrying it forever", async () => {
    // The server will say no again for the same reason. Retrying would block every
    // operation queued behind it, which is worse than losing the one.
    queue.readyOperations.mockResolvedValue([operation("a")]);
    client.api.post.mockResolvedValue({
      results: [{ opId: "a", status: "rejected", reason: "session not found" }],
    });

    const outcome = await flush();

    expect(outcome.rejected).toBe(1);
    expect(queue.removeOperations).toHaveBeenCalledWith(["a"]);
    expect(queue.recordFailure).not.toHaveBeenCalled();
  });

  it("sends the timestamp the user acted, not the time of the request", async () => {
    // A set logged at 18:40 in a basement belongs at 18:40, even if it arrives at 19:15.
    queue.readyOperations.mockResolvedValue([operation("a")]);
    client.api.post.mockResolvedValue({ results: [] });

    await flush();

    const body = client.api.post.mock.calls[0]?.[1] as {
      operations: { at: string }[];
    };
    expect(body.operations[0]?.at).toBe(new Date(1_700_000_000_000).toISOString());
  });
});

describe("being offline", () => {
  it("does not burn an operation's retries", async () => {
    // Nothing was attempted, so nothing failed. Counting this as an attempt means a
    // week in a bad signal area exhausts the queue without the server ever seeing it.
    queue.readyOperations.mockResolvedValue([operation("a")]);
    client.api.post.mockRejectedValue(new client.ApiError(0, "network_error", "No connection."));

    const outcome = await flush();

    expect(outcome.offline).toBe(true);
    expect(queue.recordFailure).not.toHaveBeenCalled();
    expect(queue.removeOperations).not.toHaveBeenCalled();
  });
});

describe("a server error", () => {
  it("records a failure so the operation backs off", async () => {
    queue.readyOperations.mockResolvedValue([operation("a"), operation("b")]);
    client.api.post.mockRejectedValue(new client.ApiError(500, "server_error", "boom"));

    await flush();

    expect(queue.recordFailure).toHaveBeenCalledTimes(2);
    expect(queue.removeOperations).not.toHaveBeenCalled();
  });
});

describe("a partial response", () => {
  it("keeps operations the server did not mention", async () => {
    // Those were never processed. Removing them here would be data loss wearing the
    // costume of a successful sync.
    queue.readyOperations.mockResolvedValue([
      operation("a"),
      operation("b"),
      operation("c"),
    ]);
    client.api.post.mockResolvedValue({
      results: [{ opId: "a", status: "applied", reason: null }],
    });

    await flush();

    expect(queue.removeOperations).toHaveBeenCalledWith(["a"]);
  });
});

describe("concurrent flushes", () => {
  it("share one request", async () => {
    // Two flushes read the same ready operations and would send them twice. The server
    // dedupes, but it is wasted bandwidth on a connection that is bad by definition.
    queue.readyOperations.mockResolvedValue([operation("a")]);
    let resolve: (value: unknown) => void = () => {};
    client.api.post.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );

    const first = flush();
    const second = flush();
    resolve({ results: [{ opId: "a", status: "applied", reason: null }] });

    await Promise.all([first, second]);
    expect(client.api.post).toHaveBeenCalledTimes(1);
  });
});
