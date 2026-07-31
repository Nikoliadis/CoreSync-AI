import { create } from "zustand";

import { tokenStore } from "@/lib/api/client";
import type { AuthenticatedUser } from "@/features/auth/types";

type AuthState = {
  user: AuthenticatedUser | null;
  /**
   * True until the first refresh attempt settles.
   *
   * The access token lives in memory, so on a hard reload we genuinely do not
   * know yet whether the user is signed in. Guards must wait for this rather
   * than bouncing to /login on every refresh.
   */
  initialising: boolean;
  signIn: (user: AuthenticatedUser, accessToken: string) => void;
  signOut: () => void;
  setUser: (user: AuthenticatedUser | null) => void;
  setInitialised: () => void;
};

export const useAuthStore = create<AuthState>()((set) => ({
  user: null,
  initialising: true,

  signIn: (user, accessToken) => {
    tokenStore.set(accessToken);
    set({ user, initialising: false });
  },

  signOut: () => {
    tokenStore.set(null);
    set({ user: null, initialising: false });
  },

  setUser: (user) => set({ user }),
  setInitialised: () => set({ initialising: false }),
}));
