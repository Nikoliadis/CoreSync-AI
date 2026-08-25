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
    pausedSeconds: 0,
    pausedAt: null,
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

describe("removing and reordering exercises", () => {
  function twoExercises() {
    const base = session();
    const first = base.exercises[0]!;
    return session({
      exercises: [
        first,
        { ...first, id: "ex-2", exerciseId: "squat", exerciseName: "Back Squat", position: 1 },
      ],
    });
  }

  it("queues a removal even when nothing under it was completed", async () => {
    // The `exercise.add` went up the moment it was chosen, so the server already holds
    // an empty entry. Skipping the removal would leave it in the user's history.
    const next = await mutations.removeExercise(session(), "ex-1");

    expect(next.exercises).toEqual([]);
    expect(queuedTypes()).toEqual(["exercise.remove"]);
  });

  it("names the session as well as the entry", async () => {
    await mutations.removeExercise(session(), "ex-1");

    const payload = queue.enqueue.mock.calls[0]?.[1] as { id: string; sessionId: string };
    expect(payload).toEqual({ id: "ex-1", sessionId: "session-1" });
  });

  it("renumbers positions so a later reorder describes the same list", async () => {
    const next = await mutations.removeExercise(twoExercises(), "ex-1");

    expect(next.exercises.map((exercise) => exercise.position)).toEqual([0]);
  });

  it("persists before it queues", async () => {
    await mutations.removeExercise(session(), "ex-1");

    expect(store.saveSession.mock.invocationCallOrder[0]).toBeLessThan(
      queue.enqueue.mock.invocationCallOrder[0]!,
    );
  });

  it("moves an exercise down and renumbers", async () => {
    const next = await mutations.moveExercise(twoExercises(), "ex-1", 1);

    expect(next.exercises.map((exercise) => exercise.id)).toEqual(["ex-2", "ex-1"]);
    expect(next.exercises.map((exercise) => exercise.position)).toEqual([0, 1]);
  });

  it("moves an exercise up", async () => {
    const next = await mutations.moveExercise(twoExercises(), "ex-2", -1);

    expect(next.exercises.map((exercise) => exercise.id)).toEqual(["ex-2", "ex-1"]);
  });

  it("queues the whole resulting order rather than a move", async () => {
    // A move ("up one place") only means something against the list the client had when
    // it was made. Replayed later it moves the wrong exercise; an absolute order is a
    // statement about the end state and survives being applied twice.
    await mutations.moveExercise(twoExercises(), "ex-1", 1);

    const [type, payload] = queue.enqueue.mock.calls[0] as [
      string,
      { sessionId: string; exerciseIds: string[] },
    ];
    expect(type).toBe("exercise.order");
    expect(payload.exerciseIds).toEqual(["ex-2", "ex-1"]);
  });

  it("does nothing at the top of the list", async () => {
    const before = twoExercises();
    const next = await mutations.moveExercise(before, "ex-1", -1);

    expect(next).toBe(before);
    expect(queue.enqueue).not.toHaveBeenCalled();
    expect(store.saveSession).not.toHaveBeenCalled();
  });

  it("does nothing at the bottom of the list", async () => {
    const before = twoExercises();
    const next = await mutations.moveExercise(before, "ex-2", 1);

    expect(next).toBe(before);
    expect(queue.enqueue).not.toHaveBeenCalled();
  });

  it("ignores an exercise that is not in the session", async () => {
    const before = twoExercises();
    expect(await mutations.moveExercise(before, "missing", 1)).toBe(before);
  });
});

describe("pausing and resuming", () => {
  it("records when the pause began, and queues nothing", async () => {
    // Local only. A pause has no meaning on its own — what it changes is the recorded
    // duration, and that is decided once, at completion.
    const next = await mutations.pauseSession(session());

    expect(next.pausedAt).not.toBeNull();
    expect(queue.enqueue).not.toHaveBeenCalled();
    expect(store.saveSession).toHaveBeenCalledOnce();
  });

  it("does nothing when already paused", async () => {
    const paused = session({ pausedAt: "2026-08-24T18:10:00.000Z" });
    expect(await mutations.pauseSession(paused)).toBe(paused);
    expect(store.saveSession).not.toHaveBeenCalled();
  });

  it("banks the pause on resume", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-24T18:10:00.000Z"));
    const next = await mutations.resumeSession(
      session({ pausedAt: "2026-08-24T18:05:00.000Z" }),
    );
    vi.useRealTimers();

    expect(next.pausedSeconds).toBe(300);
    expect(next.pausedAt).toBeNull();
  });

  it("adds a second pause to the first rather than replacing it", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-24T18:10:00.000Z"));
    const next = await mutations.resumeSession(
      session({ pausedSeconds: 120, pausedAt: "2026-08-24T18:05:00.000Z" }),
    );
    vi.useRealTimers();

    expect(next.pausedSeconds).toBe(420);
  });

  it("does nothing when not paused", async () => {
    const running = session();
    expect(await mutations.resumeSession(running)).toBe(running);
  });

  it("sends the banked time with the completion", async () => {
    await mutations.completeSession(session({ pausedSeconds: 600 }));

    const payload = queue.enqueue.mock.calls.at(-1)?.[1] as { pausedSeconds: number };
    expect(payload.pausedSeconds).toBe(600);
  });

  it("closes an open pause when the workout is finished from the paused state", async () => {
    // Otherwise the time between pausing and tapping finish counts as training.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-24T18:10:00.000Z"));
    await mutations.completeSession(session({ pausedAt: "2026-08-24T18:05:00.000Z" }));
    vi.useRealTimers();

    const payload = queue.enqueue.mock.calls.at(-1)?.[1] as { pausedSeconds: number };
    expect(payload.pausedSeconds).toBe(300);
  });

  it("sends zero for a workout that was never paused", async () => {
    await mutations.completeSession(session());

    const payload = queue.enqueue.mock.calls.at(-1)?.[1] as { pausedSeconds: number };
    expect(payload.pausedSeconds).toBe(0);
  });
});

describe("starting from a routine", () => {
  const plan = {
    id: "routine-1",
    name: "Push A",
    exercises: [
      {
        exerciseId: "bench",
        exerciseName: "Bench Press",
        restSeconds: 120,
        sets: [
          { targetRepsMin: 8, targetWeightKg: "60.00" },
          { targetRepsMin: 8, targetWeightKg: "60.00" },
        ],
      },
      {
        exerciseId: "ohp",
        exerciseName: "Overhead Press",
        restSeconds: null,
        sets: [{ targetRepsMin: 10, targetWeightKg: null }],
      },
    ],
  };

  it("lays the plan out locally in one write", async () => {
    // Not thirty writes through addExercise/addSet: that is what a six-exercise routine
    // would cost before the screen even opened.
    const session = await mutations.startRoutineSession(plan);

    expect(store.saveSession).toHaveBeenCalledOnce();
    expect(session.exercises).toHaveLength(2);
    expect(session.exercises[0]?.sets).toHaveLength(2);
  });

  it("carries the routine id so the workout is attributed to the plan", async () => {
    const session = await mutations.startRoutineSession(plan);

    expect(session.routineId).toBe("routine-1");
    const payload = queue.enqueue.mock.calls[0]?.[1] as { routineId: string };
    expect(payload.routineId).toBe("routine-1");
  });

  it("queues the create and each exercise, but no sets", async () => {
    // The prescribed rows are somewhere to type, not sets that were performed. Sending
    // them would record a workout nobody did; they go up as each one is ticked.
    await mutations.startRoutineSession(plan);

    expect(queuedTypes()).toEqual(["session.create", "exercise.add", "exercise.add"]);
  });

  it("prefills the targets onto the empty rows", async () => {
    const session = await mutations.startRoutineSession(plan);

    const first = session.exercises[0]?.sets[0];
    expect(first?.reps).toBe(8);
    expect(first?.weightKg).toBe(60);
    expect(first?.isCompleted).toBe(false);
  });

  it("leaves an unprescribed weight blank rather than zero", async () => {
    const session = await mutations.startRoutineSession(plan);

    expect(session.exercises[1]?.sets[0]?.weightKg).toBeNull();
  });

  it("numbers sets from one within each exercise", async () => {
    const session = await mutations.startRoutineSession(plan);

    expect(session.exercises[0]?.sets.map((s) => s.setNumber)).toEqual([1, 2]);
    expect(session.exercises[1]?.sets.map((s) => s.setNumber)).toEqual([1]);
  });

  it("names the session after the routine", async () => {
    const session = await mutations.startRoutineSession(plan);
    expect(session.name).toBe("Push A");
  });

  it("handles a routine with no exercises without queuing any", async () => {
    await mutations.startRoutineSession({ id: "r", name: "Empty", exercises: [] });
    expect(queuedTypes()).toEqual(["session.create"]);
  });
});
