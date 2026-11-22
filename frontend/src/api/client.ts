/**
 * The only module that talks to the network.
 *
 * - Every non-2xx response becomes an {@link ApiError} carrying the server's error code,
 *   message and offending parameter (`{"error": {code, message, param}}`).
 * - State-changing requests carry the CSRF token as `X-CSRF-Token`. The client refuses to
 *   send one without a token rather than letting the server reject it with a vaguer error.
 * - Cookies are same-origin only; the session cookie is HttpOnly and never visible here.
 */
import type { ErrorBody, RowOut } from "./types";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly param: string | null;
  /** Seconds to wait before retrying, from `Retry-After` (rate limiting). */
  readonly retryAfter: number | null;
  /** `validation_failed`: message per field name (`""` = the whole form). */
  readonly fields: Record<string, string>;
  /** `conflict`: the row as it is now on the server. */
  readonly current: RowOut | null;

  constructor(status: number, body: ErrorBody, retryAfter: number | null = null) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.param = body.param ?? null;
    this.retryAfter = retryAfter;
    this.fields = body.fields ?? {};
    this.current = body.current ?? null;
  }
}

/** Query-string values. `undefined` entries are dropped; arrays are not used by the API. */
export type QueryParams = Record<string, string | undefined>;

type Method = "GET" | "POST" | "PATCH" | "DELETE";

interface RequestOptions {
  method?: Method;
  query?: QueryParams | undefined;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal | undefined;
  /** Login is the one unsafe request made before a CSRF token exists. */
  withoutCsrf?: boolean;
}

export class ApiClient {
  readonly base: string;
  private csrfToken: string | null = null;

  /** @param base Absolute API path, e.g. `/admin/api/v1` (no trailing slash). */
  constructor(base: string) {
    this.base = base.replace(/\/+$/, "");
  }

  /** Remember the CSRF token of the current session (`null` after logout). */
  setCsrfToken(token: string | null): void {
    this.csrfToken = token;
  }

  get<T>(path: string, query?: QueryParams, signal?: AbortSignal): Promise<T> {
    return this.request<T>(path, { query, signal });
  }

  post<T>(path: string, body: unknown, options: Pick<RequestOptions, "withoutCsrf"> = {}) {
    return this.request<T>(path, { method: "POST", body, ...options });
  }

  /** A partial update guarded by the row's version (`If-Match`). */
  patch<T>(path: string, body: unknown, version: string) {
    return this.request<T>(path, { method: "PATCH", body, headers: { "if-match": version } });
  }

  delete(path: string, version: string): Promise<void> {
    return this.request<void>(path, { method: "DELETE", headers: { "if-match": version } });
  }

  /** Build the URL for `path` (relative to the API base) with `query` appended. */
  url(path: string, query?: QueryParams): string {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined) search.append(key, value);
    }
    const qs = search.toString();
    return `${this.base}${path}${qs ? `?${qs}` : ""}`;
  }

  private async request<T>(path: string, options: RequestOptions): Promise<T> {
    const method = options.method ?? "GET";
    const headers: Record<string, string> = { accept: "application/json", ...options.headers };
    if (UNSAFE_METHODS.has(method)) {
      if (options.body !== undefined) headers["content-type"] = "application/json";
      if (!options.withoutCsrf) {
        if (!this.csrfToken) {
          throw new ApiError(403, {
            code: "csrf_failed",
            message: "Your session has no CSRF token. Reload the page and try again.",
          });
        }
        headers["x-csrf-token"] = this.csrfToken;
      }
    }

    let response: Response;
    try {
      response = await fetch(this.url(path, options.query), {
        method,
        headers,
        credentials: "same-origin",
        body: options.body === undefined ? null : JSON.stringify(options.body),
        signal: options.signal ?? null,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new ApiError(0, {
        code: "network_error",
        message: "Can't reach the server. Check your connection and try again.",
      });
    }

    if (response.status === 204) return undefined as T;
    const payload: unknown = await response.json().catch(() => null);
    if (response.ok) return payload as T;
    throw toApiError(response, payload);
  }
}

function toApiError(response: Response, payload: unknown): ApiError {
  const retryAfter = Number.parseInt(response.headers.get("retry-after") ?? "", 10);
  const body = isProblem(payload)
    ? payload.error
    : { code: "http_error", message: `The server answered ${response.status}.` };
  return new ApiError(response.status, body, Number.isFinite(retryAfter) ? retryAfter : null);
}

function isProblem(value: unknown): value is { error: ErrorBody } {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as ErrorBody).code === "string" &&
    typeof (error as ErrorBody).message === "string"
  );
}

export function isApiError(error: unknown, status?: number): error is ApiError {
  return error instanceof ApiError && (status === undefined || error.status === status);
}
