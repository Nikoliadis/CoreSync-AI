import { create } from "zustand";

/**
 * The exercise handed back from the picker to the active workout.
 *
 * A one-slot handoff rather than route params. The workout needs both the id and the
 * name — the id for the server, the name to render immediately — and encoding an object
 * into a URL param is how that turns into an escaping bug. It is also read once and
 * cleared, so a stale pick cannot be applied twice if the screen remounts.
 */
export type PickedExercise = { id: string; name: string };

type State = {
  picked: PickedExercise | null;
  pick: (exercise: PickedExercise) => void;
  /** Take the pick and clear it in one step, so it can never be consumed twice. */
  consume: () => PickedExercise | null;
};

export const usePickedExercise = create<State>((set, get) => ({
  picked: null,
  pick: (exercise) => set({ picked: exercise }),
  consume: () => {
    const current = get().picked;
    if (current) set({ picked: null });
    return current;
  },
}));
