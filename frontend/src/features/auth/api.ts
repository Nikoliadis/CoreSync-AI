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

  requestPasswordReset: (email: string) =>
    api.post<void>("/v1/auth/request-password-reset", { email }, { skipAuthRefresh: true }),

  resetPassword: (token: string, newPassword: string) =>
    api.post<void>("/v1/auth/reset-password", { token, newPassword }, { skipAuthRefresh: true }),

  verifyEmail: (token: string) =>
    api.post<TokenResponse>("/v1/auth/verify-email", { token }, { skipAuthRefresh: true }),

  resendVerification: () => api.post<void>("/v1/auth/resend-verification", {}),
};
