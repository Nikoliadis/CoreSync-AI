/**
 * The single door to the API, mirroring `frontend/src/lib/api/client.ts`.
 *
 * The error envelope, the refresh coalescing and the method surface are deliberately
 * identical to the web client, so a feature written against one reads the same against
 * the other. Two things differ, and both are because this runs on a phone:
 *
 * * There are no cookies. The web app keeps its refresh token in an httpOnly cookie the
 *   browser sends automatically; a native app has to hold one itself, so it goes in
 *   `expo-secure-store` — Keychain on iOS, EncryptedSharedPreferences on Android — and
 *   is sent explicitly.
 * * The access token still lives in memory only. Persisting it would put a bearer token
 *   in storage for the sake of skipping one refresh call on launch, which is a bad
 *   trade at any price.
 */

import { secureTokens } from "@/lib/auth/secure-tokens";

export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

export type ApiErrorDetail = {
  field?: string | null;
  code: string;
  message: string;
};

/** The backend's error envelope: `{ error: { code, message, requestId, details } }`. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly details: ApiErrorDetail[];

  constructor(
    status: number,
    code: string,
    message: string,
    details: ApiErrorDetail[] = [],
    requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  /** Field-level messages, keyed for React Hook Form's `setError`. */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const detail of this.details) {
      if (detail.field) out[detail.field] = detail.message;
    }
    return out;
  }

  /**
   * True when the request never reached the server.
   *
   * Worth distinguishing: in a basement gym this is the normal case, not an error, and
   * the UI says "saved, will sync" rather than "something went wrong".
   */
  get isOffline(): boolean {
    return this.status === 0;
  }
}

let accessToken: string | null = null;
let onUnauthenticated: (() => void) | null = null;

export const tokenStore = {
  get: () => accessToken,
  set: (token: string | null) => {
    accessToken = token;
  },
  onExpired: (handler: () => void) => {
    onUnauthenticated = handler;
  },
};

/**
 * In-flight refresh, shared by every caller.
 *
 * Without this, a dashboard firing six queries on mount sends six refresh requests the
 * moment the token expires. The backend rotates refresh tokens and treats reuse as
 * theft, so the losers of that race would log the user out — a bug that appears exactly
 * fifteen minutes into a session and nowhere else.
 */
let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      const refreshToken = await secureTokens.getRefreshToken();
      if (!refreshToken) return false;

      const response = await fetch(`${API_BASE_URL}/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refreshToken }),
      });
      if (!response.ok) return false;

      const data = (await response.json()) as {
        accessToken?: string;
        refreshToken?: string;
      };
      if (!data.accessToken) return false;

      accessToken = data.accessToken;
      // The backend rotates on every refresh, so the old one is already dead. Storing
      // the new one immediately is what keeps the next cold start working.
      if (data.refreshToken) await secureTokens.setRefreshToken(data.refreshToken);
      return true;
    } catch {
      return false;
    } finally {
      queueMicrotask(() => {
        refreshInFlight = null;
      });
    }
  })();

  return refreshInFlight;
}

type RequestOptions = {
  body?: unknown;
  headers?: Record<string, string>;
  /** Set for the auth endpoints themselves, which must not trigger a refresh loop. */
  skipAuthRefresh?: boolean;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
};

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(`${API_BASE_URL}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = "unknown_error";
  let message = "Something went wrong. Please try again.";
  let details: ApiErrorDetail[] = [];
  let requestId: string | undefined;

  try {
    const body = (await response.json()) as {
      error?: {
        code?: string;
        message?: string;
        requestId?: string;
        details?: ApiErrorDetail[];
      };
    };
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details ?? [];
      requestId = body.error.requestId;
    }
  } catch {
    // A response with no JSON body — a gateway error page, usually. The defaults above
    // are already the right thing to show.
  }

  return new ApiError(response.status, code, message, details, requestId);
}

/**
 * Whether a rejection is a deliberate cancellation rather than a failure.
 *
 * A cancelled request is the caller's own doing — a screen dismissed, a search
 * superseded — and must propagate untouched rather than being reported to the user as a
 * dead connection.
 */
function isAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      // Lets the backend reject builds too old to understand a response, rather than
      // letting them fail in some subtler way in front of a user.
      "X-Client-Version": `mobile/${process.env.EXPO_PUBLIC_APP_VERSION ?? "dev"}`,
      ...options.headers,
    };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

    return fetch(buildUrl(path, options.query), {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  };

  let response: Response;
  try {
    response = await send();
  } catch (error) {
    // Checked by name rather than `instanceof DOMException`.
    //
    // Hermes has no `DOMException` at all, so the `instanceof` threw a ReferenceError
    // *inside this catch block* — which replaced whatever actually failed with a
    // meaningless one, on every rejected request. The name is the part that carries the
    // meaning anyway, and it is the same on both platforms.
    if (isAbort(error)) throw error;
    // Status 0 means "never reached the server". Callers use `isOffline` to tell a dead
    // connection from a rejection, because in a gym those need different words.
    throw new ApiError(0, "network_error", "No connection.");
  }

  if (response.status === 401 && !options.skipAuthRefresh) {
    if (await refreshAccessToken()) {
      response = await send();
    } else {
      accessToken = null;
      await secureTokens.clear();
      onUnauthenticated?.();
    }
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;

  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PATCH", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PUT", path, { ...options, body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>("DELETE", path, options),
};
