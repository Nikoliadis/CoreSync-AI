/**
 * The single door to the API (docs/07 §3.5).
 *
 * Everything the network needs lives here: base URL, auth header, silent token
 * refresh, and translation of the backend's error envelope into a typed error.
 * Features call `api.get(...)`, never `fetch` — so a change to auth or tracing
 * is one edit, not forty.
 */

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
}

// ---------------------------------------------------------------- token store
/**
 * The access token is held in memory only.
 *
 * localStorage would make it readable by any injected script; the refresh token
 * lives in an httpOnly cookie the backend sets for web clients, so a reload
 * restores the session through `/auth/refresh` rather than by persisting a
 * bearer token where XSS can reach it (docs/06, docs/11).
 */
let accessToken: string | null = null;
let onUnauthenticated: (() => void) | null = null;

export const tokenStore = {
  get: () => accessToken,
  set: (token: string | null) => {
    accessToken = token;
  },
  /** Called when refresh fails — the app clears its cache and returns to login. */
  onExpired: (handler: () => void) => {
    onUnauthenticated = handler;
  },
};

// ------------------------------------------------------------------- refresh
/**
 * In-flight refresh, shared by every caller.
 *
 * Without this, a dashboard that fires six queries on mount sends six refresh
 * requests the moment the token expires. The backend rotates refresh tokens and
 * treats reuse as theft, so the losers of that race would log the user out —
 * a bug that only appears exactly 15 minutes into a session.
 */
let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/v1/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!response.ok) return false;
      const data = (await response.json()) as { accessToken?: string };
      if (!data.accessToken) return false;
      accessToken = data.accessToken;
      return true;
    } catch {
      return false;
    } finally {
      // Cleared in a microtask so simultaneous callers all observe the same
      // promise before it is torn down.
      queueMicrotask(() => {
        refreshInFlight = null;
      });
    }
  })();

  return refreshInFlight;
}

// ------------------------------------------------------------------- request
type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  /** Set for the auth endpoints themselves, which must not trigger a refresh loop. */
  skipAuthRefresh?: boolean;
  query?: Record<string, string | number | boolean | undefined | null>;
};

function buildUrl(path: string, query?: RequestOptions["query"]) {
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
      error?: { code?: string; message?: string; requestId?: string; details?: ApiErrorDetail[] };
    };
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details ?? [];
      requestId = body.error.requestId;
    }
  } catch {
    // A non-JSON body (a gateway error page, say) still has a useful status.
    if (response.status >= 500) message = "The server is having trouble. Please try again shortly.";
  }

  return new ApiError(response.status, code, message, details, requestId);
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const { body, skipAuthRefresh, query, headers, ...rest } = options;

  const send = async (): Promise<Response> =>
    fetch(buildUrl(path, query), {
      ...rest,
      method,
      credentials: "include",
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

  let response = await send();

  // One retry, and only for an expired token. A 401 that survives a successful
  // refresh is a real authorisation failure, not a stale credential.
  if (response.status === 401 && !skipAuthRefresh) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      response = await send();
    } else {
      accessToken = null;
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
  delete: <T>(path: string, options?: RequestOptions) => request<T>("DELETE", path, options),
  refresh: refreshAccessToken,
};
