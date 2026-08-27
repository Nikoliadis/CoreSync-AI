import { create } from "zustand";

import { ApiError, api, tokenStore } from "@/lib/api/client";
import { secureTokens } from "@/lib/auth/secure-tokens";
import { identifyUser } from "@/lib/telemetry/crash-reporting";
import { clearUserData } from "@/offline/database";

export type AuthUser = {
  id: string;
  email: string;
  displayName: string;
  timezone: string;
};

type TokenPair = { accessToken: string; refreshToken: string; user?: AuthUser };

type AuthState = {
  user: AuthUser | null;
  /** Null until the first restore attempt finishes — distinct from "logged out". */
  status: "restoring" | "authenticated" | "anonymous";
  restore: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  /**
   * Exchange a verified provider token for a CoreSync session.
   *
   * The same session path as `login` on purpose: refresh, restore, logout and the token
   * store all behave identically afterwards, because what comes back is a CoreSync token
   * pair and nothing about the provider survives the exchange.
   */
  signInWithProvider: (input: {
    provider: "apple" | "google";
    idToken: string;
    nonce?: string;
    displayName?: string | null;
  }) => Promise<void>;
  register: (input: {
    email: string;
    password: string;
    displayName: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
};

/**
 * Session state.
 *
 * `status` has three values rather than a boolean because the gap between them is a
 * real screen: on a cold start the app does not yet know whether it is logged in, and
 * showing the login page during that moment would flash it at every returning user.
 */
export const useAuth = create<AuthState>((set) => ({
  user: null,
  status: "restoring",

  async restore() {
    const refreshToken = await secureTokens.getRefreshToken();
    if (!refreshToken) {
      set({ status: "anonymous", user: null });
      return;
    }
    try {
      const tokens = await api.post<TokenPair>(
        "/v1/auth/refresh",
        { refreshToken },
        { skipAuthRefresh: true },
      );
      tokenStore.set(tokens.accessToken);
      await secureTokens.setRefreshToken(tokens.refreshToken);
      const user = tokens.user ?? (await api.get<AuthUser>("/v1/users/me"));
      identifyUser(user.id);
      set({ status: "authenticated", user });
    } catch {
      // An expired or revoked token is a logged-out user, not an error to show.
      await secureTokens.clear();
      identifyUser(null);
      set({ status: "anonymous", user: null });
    }
  },

  async login(email, password) {
    const tokens = await api.post<TokenPair>(
      "/v1/auth/login",
      { email, password },
      { skipAuthRefresh: true },
    );
    tokenStore.set(tokens.accessToken);
    await secureTokens.setRefreshToken(tokens.refreshToken);
    const user = tokens.user ?? (await api.get<AuthUser>("/v1/users/me"));
    identifyUser(user.id);
    set({ status: "authenticated", user });
  },

  async signInWithProvider({ provider, idToken, nonce, displayName }) {
    const tokens = await api.post<TokenPair>(
      `/v1/auth/oauth/${provider}`,
      {
        idToken,
        nonce,
        // Apple returns a name only on the first authorisation. Forwarding it here is
        // the single opportunity to persist it; there is no later call that has it.
        displayName: displayName ?? undefined,
      },
      { skipAuthRefresh: true },
    );

    tokenStore.set(tokens.accessToken);
    await secureTokens.setRefreshToken(tokens.refreshToken);
    const user = tokens.user ?? (await api.get<AuthUser>("/v1/users/me"));
    identifyUser(user.id);
    set({ status: "authenticated", user });
  },

  async register({ email, password, displayName }) {
    await api.post(
      "/v1/auth/register",
      {
        email,
        password,
        displayName,
        // Sent from the device so streaks, diary dates and quota resets land on the
        // user's day rather than UTC's.
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        acceptedTerms: true,
      },
      { skipAuthRefresh: true },
    );
  },

  async logout() {
    // Before the token is discarded, while the request can still authenticate. Leaving
    // the device registered means the next notification for this account arrives on a
    // phone that somebody else may now be signed into.
    const { unregisterCurrentDevice } = await import("@/features/notifications/push");
    await unregisterCurrentDevice();

    try {
      await api.post("/v1/auth/logout", {});
    } catch (error) {
      // Already invalid server-side, or no connection. Either way the local session is
      // going away — a logout that fails because you are offline would be absurd.
      if (!(error instanceof ApiError)) throw error;
    }
    tokenStore.set(null);
    identifyUser(null);
    await secureTokens.clear();
    await clearUserData();
    set({ status: "anonymous", user: null });
  },
}));
