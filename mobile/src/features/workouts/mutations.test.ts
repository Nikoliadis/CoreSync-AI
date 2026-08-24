import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The offline write path.
 *
 * Two properties are being defended here, and both are about what reaches the server.
 *
 * The first is that local state is written *before* anything is queued, and that neither
 * depends on a network call. A user in a basement finishes a whole workout; nothing in
 * this file may await a request.
 *
 * The second is that only real data is queued. An empty set row is a place to type, not
 * a set — sending it would put a set with no reps and no weight into somebody's history
 * the moment they tapped "add", and it would be there forever.
 */

const store = vi.hoisted(() => ({
  saveSession: vi.fn(),
  deleteSession: vi.fn(),
}));

const queue = vi.hoisted(() => ({ enqueue: vi.fn() }));

// Only persistence is stubbed. The model is pure and runs for real, so set numbering
// and renumbering are genuinely exercised rather than asserted against a mock.
vi.mock("./local-store", () => store);
vi.mock("@/offline/queue", () => queue);

const mutations = await import("./mutations");

function session(overrides: Partial<import("./session-model").LocalSession> = {}) {
  return {
    id: "session-1",
    name: "Push day",
    routineId: null,
    startedAt: "2026-08-24T18:00:00.000Z",
    completedAt: null,
    notes: null,
    exercises: [
      {
        id: "ex-1",
        exerciseId: "bench",
        exerciseName: "Bench Press",
        position: 0,
        notes: null,
        restSeconds: 90,
        sets: [
          {
            id: "set-1",
            sessionExerciseId: "ex-1",
            setNumber: 1,
            setType: "normal" as const,
            reps: 8,
            weightKg: 80,
            rpe: null,
            isCompleted: false,
            completedAt: null,
          },
        ],
      },
    ],
    ...overrides,
  };
}

function queuedTypes(): string[] {
  return queue.enqueue.mock.calls.map((call) => call[0] as string);
}

beforeEach(() => {
  vi.clearAllMocks();
  store.saveSession.mockResolvedValue(undefined);
  store.deleteSession.mockResolvedValue(undefined);
  queue.enqueue.mockResolvedValue("op-1");
});

describe("starting a session", () => {
  it("persists locally and queues a create", async () => {
    await mutations.startSession(session());

    expect(store.saveSession).toHaveBeenCalledOnce();
    expect(queuedTypes()).toEqual(["session.create"]);
  });

  it("sends the client id as the server id", async () => {
    // The whole reason ids are minted on the device: a replayed flush is one session.
    await mutations.startSession(session());

    const payload = queue.enqueue.mock.calls[0]?.[1] as { id: string; clientSessionId: string };
    expect(payload.id).toBe("session-1");
    expect(payload.clientSessionId).toBe("session-1");
  });
});

describe("adding a set", () => {
  it("saves locally but queues nothing", async () => {
    // An empty row is somewhere to type. Queuing it would write a set with no reps and
    // no weight into the user's history the instant they tapped add.
    const next = await mutations.addSet(session(), "ex-1");

    expect(store.saveSession).toHaveBeenCalledOnce();
    expect(queue.enqueue).not.toHaveBeenCalled();
    expect(next.exercises[0]?.sets).toHaveLength(2);
  });

  it("numbers the new set after the last", async () => {
    const next = await mutations.addSet(session(), "ex-1");
    expect(next.exercises[0]?.sets[1]?.setNumber).toBe(2);
  });

  it("ignores an exercise that is not in the session", async () => {
    const current = session();
    const next = await mutations.addSet(current, "missing");
    expect(next).toBe(current);
    expect(store.saveSession).not.toHaveBeenCalled();
  });
});

describe("completing a set", () => {
  it("marks it locally and queues a log", async () => {
    const next = await mutations.completeSet(session(), "ex-1", "set-1");

    expect(next.exercises[0]?.sets[0]?.isCompleted).toBe(true);
    expect(queuedTypes()).toEqual(["set.log"]);
  });

  it("sends the numbers that were on screen", async () => {
    await mutations.completeSet(session(), "ex-1", "set-1");

    const payload = queue.enqueue.mock.calls[0]?.[1] as { reps: number; weightKg: number };
    expect(payload.reps).toBe(8);
    expect(payload.weightKg).toBe(80);
  });

  it("stamps when it happened", async () => {
    // Not when it syncs. A set completed at 18:40 in a basement belongs at 18:40.
    const next = await mutations.completeSet(session(), "ex-1", "set-1");
    expect(next.exercises[0]?.sets[0]?.completedAt).toBeTruthy();
  });

  it("never awaits the network", async () => {
    // The assertion is the absence of a fetch. If one is ever introduced here, a user
    // in a basement stops being able to log.
    const spy = vi.spyOn(globalThis, "fetch");
    await mutations.completeSet(session(), "ex-1", "set-1");
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe("editing a set", () => {
  it("queues nothing while the set is incomplete", async () => {
    await mutations.updateSet(session(), "ex-1", "set-1", { reps: 10 });

    expect(store.saveSession).toHaveBeenCalledOnce();
    expect(queue.enqueue).not.toHaveBeenCalled();
  });

  it("queues an update once the set is completed", async () => {
    const completed = session();
    completed.exercises[0]!.sets[0]!.isCompleted = true;

    await mutations.updateSet(completed, "ex-1", "set-1", { reps: 10 });
    expect(queuedTypes()).toEqual(["set.update"]);
  });
});

describe("unticking a set", () => {
  it("tells the server it is no longer complete", async () => {
    const next = await mutations.uncompleteSet(session(), "ex-1", "set-1");

    expect(next.exercises[0]?.sets[0]?.isCompleted).toBe(false);
    expect(queuedTypes()).toEqual(["set.update"]);
  });
});

describe("deleting a set", () => {
  it("does not queue a delete for a set the server never saw", async () => {
    await mutations.deleteSet(session(), "ex-1", "set-1");

    expect(store.saveSession).toHaveBeenCalledOnce();
    expect(queue.enqueue).not.toHaveBeenCalled();
  });

  it("queues a delete for a completed set", async () => {
    const completed = session();
    completed.exercises[0]!.sets[0]!.isCompleted = true;

    await mutations.deleteSet(completed, "ex-1", "set-1");
    expect(queuedTypes()).toEqual(["set.delete"]);
  });

  it("renumbers what is left", async () => {
    const three = session();
    three.exercises[0]!.sets = [1, 2, 3].map((n) => ({
      id: `set-${n}`,
      sessionExerciseId: "ex-1",
      setNumber: n,
      setType: "normal" as const,
      reps: 8,
      weightKg: 80,
      rpe: null,
      isCompleted: false,
      completedAt: null,
    }));

    const next = await mutations.deleteSet(three, "ex-1", "set-2");
    expect(next.exercises[0]?.sets.map((s) => s.setNumber)).toEqual([1, 2]);
  });
});

describe("finishing", () => {
  it("stamps completion and queues it", async () => {
    const next = await mutations.completeSession(session());

    expect(next.completedAt).toBeTruthy();
    expect(queuedTypes()).toEqual(["session.complete"]);
  });
});

describe("discarding", () => {
  it("tells the server and clears local state", async () => {
    // Both are needed: an earlier flush may already have put sets on the server, and
    // deleting locally alone would leave them there forever.
    await mutations.discardSession(session());

    expect(queuedTypes()).toEqual(["session.discard"]);
    expect(store.deleteSession).toHaveBeenCalledWith("session-1");
  });
});

describe("every queued operation type", () => {
  it("is one the server dispatches on", async () => {
    // The server answers an unknown type with `rejected`, and a rejection is terminal —
    // so a typo here is silent data loss rather than an error anybody sees.
    const HANDLED = new Set([
      "session.create",
      "session.update",
      "exercise.add",
      "set.log",
      "set.update",
      "set.delete",
      "session.complete",
      "session.discard",
    ]);

    const completed = session();
    completed.exercises[0]!.sets[0]!.isCompleted = true;

    await mutations.startSession(session());
    await mutations.completeSet(session(), "ex-1", "set-1");
    await mutations.updateSet(completed, "ex-1", "set-1", { reps: 9 });
    await mutations.uncompleteSet(session(), "ex-1", "set-1");
    await mutations.deleteSet(completed, "ex-1", "set-1");
    await mutations.updateNotes(session(), "felt strong");
    await mutations.completeSession(session());
    await mutations.discardSession(session());

    for (const type of queuedTypes()) {
      expect(HANDLED.has(type), `${type} is not handled by the server`).toBe(true);
    }
  });
});
