import { api } from "@/lib/api/client";
import type { LoginPayload, RegisterPayload, TokenResponse } from "@/features/auth/types";

export const authApi = {
  register: (payload: RegisterPayload) =>
    // `skipAuthRefresh` on every auth call: a 401 here means bad credentials,
    // and attempting a refresh would both fail and mask the real error.
    api.post<TokenResponse>("/v1/auth/register", payload, { skipAuthRefresh: true }),

  login: (payload: LoginPayload) =>
    api.post<TokenResponse>("/v1/auth/login", payload, { skipAuthRefresh: true }),

  logout: () => api.post<void>("/v1/auth/logout", {}),

  /**
   * Exchange a provider ID token for a CoreSync session.
   *
   * The client never sees a client *secret* — this is the ID-token flow, so the browser
   * receives a signed assertion and the backend verifies it against the provider's JWKS.
   * Nothing here is a credential that could be stolen from the bundle.
   *
   * `displayName` exists for Apple, which returns the user's name only on the very first
   * authorisation and never again. Forwarding it is the one chance to persist it.
   */
  oauthSignIn: (
    provider: "google" | "apple",
    payload: { idToken: string; nonce?: string; displayName?: string },
  ) =>
    api.post<TokenResponse>(`/v1/auth/oauth/${provider}`, payload, {
      skipAuthRefresh: true,
    }),

  requestPasswordReset: (email: string) =>
    api.post<void>("/v1/auth/request-password-reset", { email }, { skipAuthRefresh: true }),

  resetPassword: (token: string, newPassword: string) =>
    api.post<void>("/v1/auth/reset-password", { token, newPassword }, { skipAuthRefresh: true }),

  verifyEmail: (token: string) =>
    api.post<TokenResponse>("/v1/auth/verify-email", { token }, { skipAuthRefresh: true }),

  resendVerification: () => api.post<void>("/v1/auth/resend-verification", {}),
};
