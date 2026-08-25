import { create } from "zustand";

import type { MealType } from "./api";

/**
 * The food chosen in search, handed back to the diary.
 *
 * The same one-slot pattern the exercise picker uses: route params would carry the id
 * but not the serving and quantity, and encoding an object into a URL is where that goes
 * wrong. Read once and cleared, so a stale pick cannot be logged twice if the tab
 * remounts.
 */
export type PickedFood = {
  foodId: string;
  mealType: MealType;
  quantity: number;
  servingId: string | null;
};

type State = {
  picked: PickedFood | null;
  pick: (food: PickedFood) => void;
  /** Take the pick and clear it in one step, so it can never be consumed twice. */
  consume: () => PickedFood | null;
};

export const usePickedFood = create<State>((set, get) => ({
  picked: null,
  pick: (food) => set({ picked: food }),
  consume: () => {
    const current = get().picked;
    if (current) set({ picked: null });
    return current;
  },
}));
