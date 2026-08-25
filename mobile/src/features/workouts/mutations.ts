/**
 * Every workout write, offline-first.
 *
 * The shape is the same for all of them and the order is the whole point:
 *
 *   1. mutate local state and persist it
 *   2. append an operation to the write-ahead log
 *   3. return
 *
 * The network is not in that list. A caller never awaits a request, never handles a
 * network error, and never shows a spinner — the write is already durable by the time it
 * returns, and the sync engine deals with the rest whenever there is a connection.
 *
 * Ids are minted locally and reused as the server's primary key, so a queue flushed
 * twice produces one set rather than two.
 */

import { enqueue } from "@/offline/queue";

import { saveSession } from "./local-store";
import {
  type LocalExercise,
  type LocalSession,
  type LocalSet,
  type SetType,
  newExercise,
  newSet,
} from "./session-model";

/** Immutably replace one exercise in a session. */
function withExercise(
  session: LocalSession,
  exerciseId: string,
  update: (exercise: LocalExercise) => LocalExercise,
): LocalSession {
  return {
    ...session,
    exercises: session.exercises.map((exercise) =>
      exercise.id === exerciseId ? update(exercise) : exercise,
    ),
  };
}

export async function startSession(session: LocalSession): Promise<LocalSession> {
  await saveSession(session);
  await enqueue("session.create", {
    id: session.id,
    clientSessionId: session.id,
    routineId: session.routineId,
    name: session.name,
    startedAt: session.startedAt,
  });
  return session;
}

export async function addExercise(
  session: LocalSession,
  input: { exerciseId: string; exerciseName: string; restSeconds?: number | null },
): Promise<LocalSession> {
  const exercise = newExercise({ ...input, position: session.exercises.length });
  const next: LocalSession = { ...session, exercises: [...session.exercises, exercise] };

  await saveSession(next);
  await enqueue("exercise.add", {
    id: exercise.id,
    sessionId: session.id,
    exerciseId: exercise.exerciseId,
    restSeconds: exercise.restSeconds,
  });
  return next;
}

/**
 * Take an exercise back out of the session.
 *
 * Always queued, even when nothing under it was ever completed. The `exercise.add` went
 * up the moment it was chosen — the server has the entry whether or not it has any sets
 * — so skipping the removal would leave an empty exercise in the user's history that
 * they explicitly took out.
 */
export async function removeExercise(
  session: LocalSession,
  exerciseId: string,
): Promise<LocalSession> {
  const next: LocalSession = {
    ...session,
    exercises: session.exercises
      .filter((exercise) => exercise.id !== exerciseId)
      // Renumber so positions stay 0..n-1 and a later reorder is describing the same
      // list the server holds.
      .map((exercise, index) => ({ ...exercise, position: index })),
  };

  await saveSession(next);
  await enqueue("exercise.remove", { id: exerciseId, sessionId: session.id });
  return next;
}

/**
 * Move an exercise up or down.
 *
 * Queued as the full resulting order rather than "this one, up one place". A move only
 * means something against the list the client had when it was made; replayed later it
 * moves the wrong exercise. An absolute order is a statement about the end state, so it
 * survives being applied twice or out of step with the rest of the batch.
 */
export async function moveExercise(
  session: LocalSession,
  exerciseId: string,
  direction: -1 | 1,
): Promise<LocalSession> {
  const from = session.exercises.findIndex((exercise) => exercise.id === exerciseId);
  const to = from + direction;
  if (from === -1 || to < 0 || to >= session.exercises.length) return session;

  const exercises = [...session.exercises];
  const [moved] = exercises.splice(from, 1);
  if (!moved) return session;
  exercises.splice(to, 0, moved);

  const next: LocalSession = {
    ...session,
    exercises: exercises.map((exercise, index) => ({ ...exercise, position: index })),
  };

  await saveSession(next);
  await enqueue("exercise.order", {
    sessionId: session.id,
    exerciseIds: next.exercises.map((exercise) => exercise.id),
  });
  return next;
}

export async function addSet(
  session: LocalSession,
  exerciseId: string,
  input: { reps?: number | null; weightKg?: number | null; setType?: SetType } = {},
): Promise<LocalSession> {
  const exercise = session.exercises.find((item) => item.id === exerciseId);
  if (!exercise) return session;

  const set = newSet({
    sessionExerciseId: exerciseId,
    setNumber: exercise.sets.length + 1,
    ...input,
  });

  const next = withExercise(session, exerciseId, (item) => ({
    ...item,
    sets: [...item.sets, set],
  }));

  // Not queued yet. An empty set row is a UI affordance — somewhere to type — and
  // sending it would put a set with no reps and no weight into the user's history the
  // moment they tap "add". It goes up when it is completed.
  await saveSession(next);
  return next;
}

export async function updateSet(
  session: LocalSession,
  exerciseId: string,
  setId: string,
  changes: Partial<Pick<LocalSet, "reps" | "weightKg" | "rpe" | "setType">>,
): Promise<LocalSession> {
  let updated: LocalSet | null = null;

  const next = withExercise(session, exerciseId, (exercise) => ({
    ...exercise,
    sets: exercise.sets.map((set) => {
      if (set.id !== setId) return set;
      updated = { ...set, ...changes };
      return updated;
    }),
  }));

  await saveSession(next);

  // Only an already-completed set is worth telling the server about. Editing one that
  // has not been ticked is still typing.
  if (updated && (updated as LocalSet).isCompleted) {
    await enqueue("set.update", {
      id: setId,
      sessionId: session.id,
      sessionExerciseId: exerciseId,
      ...changes,
    });
  }
  return next;
}

/**
 * Tick a set. The single most repeated action in the product.
 *
 * Completion is what makes a set real: it is the moment it counts toward volume, toward
 * a personal record, and toward the queue.
 */
export async function completeSet(
  session: LocalSession,
  exerciseId: string,
  setId: string,
): Promise<LocalSession> {
  const completedAt = new Date().toISOString();
  let completed: LocalSet | null = null;

  const next = withExercise(session, exerciseId, (exercise) => ({
    ...exercise,
    sets: exercise.sets.map((set) => {
      if (set.id !== setId) return set;
      completed = { ...set, isCompleted: true, completedAt };
      return completed;
    }),
  }));

  await saveSession(next);

  if (completed) {
    const set = completed as LocalSet;
    await enqueue("set.log", {
      id: set.id,
      sessionId: session.id,
      sessionExerciseId: exerciseId,
      setNumber: set.setNumber,
      setType: set.setType,
      reps: set.reps,
      weightKg: set.weightKg,
      rpe: set.rpe,
      isCompleted: true,
      completedAt,
    });
  }
  return next;
}

/** Untick. Local only — the server hears about it as a `set.update`. */
export async function uncompleteSet(
  session: LocalSession,
  exerciseId: string,
  setId: string,
): Promise<LocalSession> {
  const next = withExercise(session, exerciseId, (exercise) => ({
    ...exercise,
    sets: exercise.sets.map((set) =>
      set.id === setId ? { ...set, isCompleted: false, completedAt: null } : set,
    ),
  }));

  await saveSession(next);
  await enqueue("set.update", {
    id: setId,
    sessionId: session.id,
    sessionExerciseId: exerciseId,
    isCompleted: false,
  });
  return next;
}

export async function deleteSet(
  session: LocalSession,
  exerciseId: string,
  setId: string,
): Promise<LocalSession> {
  const exercise = session.exercises.find((item) => item.id === exerciseId);
  const existing = exercise?.sets.find((set) => set.id === setId);

  const next = withExercise(session, exerciseId, (item) => ({
    ...item,
    sets: item.sets
      .filter((set) => set.id !== setId)
      // Renumber so the display stays 1..n. The server renumbers too, from the same
      // ordering, so the two do not drift.
      .map((set, index) => ({ ...set, setNumber: index + 1 })),
  }));

  await saveSession(next);

  // A set the server never saw needs no deletion — it was never sent.
  if (existing?.isCompleted) {
    await enqueue("set.delete", {
      id: setId,
      sessionId: session.id,
      sessionExerciseId: exerciseId,
    });
  }
  return next;
}

export async function updateNotes(
  session: LocalSession,
  notes: string,
): Promise<LocalSession> {
  const next = { ...session, notes };
  await saveSession(next);
  await enqueue("session.update", { id: session.id, name: session.name, notes });
  return next;
}

/**
 * Stop the clock.
 *
 * Local only — nothing is queued. The server is told once, at completion, because a
 * pause has no meaning on its own: what it changes is the recorded duration, and that is
 * decided when the workout ends. Queuing every pause and resume would put a stream of
 * operations on the wire to describe a number that can be sent as one.
 */
export async function pauseSession(session: LocalSession): Promise<LocalSession> {
  if (session.pausedAt) return session;

  const next: LocalSession = { ...session, pausedAt: new Date().toISOString() };
  await saveSession(next);
  return next;
}

export async function resumeSession(session: LocalSession): Promise<LocalSession> {
  if (!session.pausedAt) return session;

  const paused = (Date.now() - Date.parse(session.pausedAt)) / 1000;
  const next: LocalSession = {
    ...session,
    // Banked on resume rather than recomputed at the end, so several pauses in one
    // session add up instead of the last one winning.
    pausedSeconds: (session.pausedSeconds ?? 0) + Math.max(0, Math.floor(paused)),
    pausedAt: null,
  };
  await saveSession(next);
  return next;
}

export async function completeSession(session: LocalSession): Promise<LocalSession> {
  // Finishing while paused ends the pause: the time up to now was still not training.
  const settled = session.pausedAt ? await resumeSession(session) : session;
  const completedAt = new Date().toISOString();
  const next = { ...settled, completedAt };

  await saveSession(next, "local");
  await enqueue("session.complete", {
    id: session.id,
    completedAt,
    pausedSeconds: next.pausedSeconds ?? 0,
  });
  return next;
}

/**
 * Throw the session away.
 *
 * Queued *and* deleted locally. The server may already have some of its sets from an
 * earlier flush, so telling it to discard is the only way the two agree.
 */
export async function discardSession(session: LocalSession): Promise<void> {
  await enqueue("session.discard", { id: session.id });
  const { deleteSession } = await import("./local-store");
  await deleteSession(session.id);
}
