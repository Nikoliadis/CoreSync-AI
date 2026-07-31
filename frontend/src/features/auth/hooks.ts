"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect } from "react";

import { authApi } from "@/features/auth/api";
import { useAuthStore } from "@/features/auth/store";
import type { LoginPayload, MeResponse, RegisterPayload } from "@/features/auth/types";
import { api, tokenStore } from "@/lib/api/client";

/**
 * Restores the session on first mount and after a hard reload.
 *
 * The access token is deliberately not persisted, so "am I logged in?" can only
 * be answered by asking the backend to exchange the httpOnly refresh cookie.
 * Until that settles, guards show a loading state rather than redirecting.
 */
export function useSessionBootstrap() {
  const setUser = useAuthStore((s) => s.setUser);
  const setInitialised = useAuthStore((s) => s.setInitialised);
  const signOut = useAuthStore((s) => s.signOut);
  const queryClient = useQueryClient();
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;

    // A refresh failure anywhere in the app lands here: clear the cache so the
    // next user does not see the previous one's data, then return to login.
    tokenStore.onExpired(() => {
      signOut();
      queryClient.clear();
      router.replace("/login");
    });

    void (async () => {
      const refreshed = await api.refresh();
      if (cancelled) return;

      if (refreshed) {
        try {
          // `/users/me` is the app-boot call: user, profile, goal, targets and
          // settings in one round trip. Only the user is needed to unblock the
          // guard; the rest is fetched by the screens that use it.
          const me = await api.get<MeResponse>("/v1/users/me");
          if (!cancelled) setUser(me.user);
        } catch {
          if (!cancelled) signOut();
        }
      }
      if (!cancelled) setInitialised();
    })();

    return () => {
      cancelled = true;
    };
  }, [queryClient, router, setInitialised, setUser, signOut]);
}

export function useAuthActions() {
  const signIn = useAuthStore((s) => s.signIn);
  const signOutStore = useAuthStore((s) => s.signOut);
  const queryClient = useQueryClient();
  const router = useRouter();

  const login = useCallback(
    async (payload: LoginPayload) => {
      const tokens = await authApi.login(payload);
      signIn(tokens.user, tokens.accessToken);
      return tokens;
    },
    [signIn],
  );

  const register = useCallback(
    async (payload: RegisterPayload) => {
      const tokens = await authApi.register(payload);
      signIn(tokens.user, tokens.accessToken);
      return tokens;
    },
    [signIn],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // A failed logout call must still clear the client. The token is revoked
      // server-side on expiry regardless, and leaving the user apparently signed
      // in on a shared machine is the worse outcome.
    }
    signOutStore();
    queryClient.clear();
    router.replace("/login");
  }, [queryClient, router, signOutStore]);

  return { login, register, logout };
}

export function useCurrentUser() {
  return useAuthStore((s) => s.user);
}
