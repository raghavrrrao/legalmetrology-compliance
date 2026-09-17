/**
 * The single HTTP client for talking to the Django REST API.
 *
 * Every request in the app goes through here - the same rule as
 * `frontend/src/services/apiClient.js`, and for the same reason: one place to
 * handle the API's error envelope, timeouts and URL joining, rather than a
 * different `fetch` call on every screen.
 *
 * The backend returns errors in a fixed shape (see docs/api.md):
 *
 *     { "error": { "code": "...", "message": "...", "details": ... } }
 *
 * `ApiError` carries that through unchanged, so a screen can branch on
 * `error.code` instead of matching on English text.
 *
 * What is deliberately NOT here:
 *
 * - **No credentials.** The analysis endpoints are reached anonymously under
 *   the backend's `DEMO_PUBLIC_ANALYSIS_API` switch (docs/api.md, "Permissions
 *   on the six analysis endpoints"). That is a controlled demonstration
 *   arrangement, not the final security model. When a token or session scheme
 *   lands, the `headers` option below is the one seam it plugs into.
 * - **No CSRF token.** The web client attaches Django's CSRF cookie because a
 *   browser sends the session cookie automatically. This client holds no
 *   session, so there is nothing to protect and nothing to attach.
 * - **No logging of request bodies.** A body is a photograph of somebody's
 *   product; it is never written to the console.
 */

import { config } from '../config/env';
import type { ApiErrorEnvelope } from '../types/api';

/** Requests that take longer than this are aborted. */
export const DEFAULT_TIMEOUT_MS = 15000;

/** Stable error codes this client produces itself, alongside the backend's. */
export type ClientErrorCode =
  | 'network_error'
  | 'timeout'
  | 'invalid_json'
  | 'unexpected_response';

export interface ApiErrorOptions {
  status?: number;
  code?: string;
  details?: unknown;
}

/**
 * An API request that failed, with the backend's structured error attached.
 *
 * `code` is stable and safe to branch on. `message` is safe to display: it is
 * either the backend's own user-facing message or one written here. `status`
 * is 0 when the request never reached the server (no network, DNS failure,
 * timeout) - which is a different problem from a 500, and the UI says so.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(message: string, { status = 0, code = 'network_error', details = null }: ApiErrorOptions = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** True when the request never got an answer from the server. */
  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

/**
 * A file as React Native's `FormData` expects it: a local `uri` plus the
 * `name` and `type` the multipart part is sent with. There is no `File` or
 * `Blob` on the native side; the networking layer reads the uri itself.
 */
export interface UploadFile {
  uri: string;
  name: string;
  type: string;
}

export interface RequestOptions {
  method?: 'GET' | 'POST';
  /** JSON-serialised automatically. */
  body?: unknown;
  /** For file uploads. Content-Type is left to the runtime, which adds the multipart boundary. */
  formData?: FormData;
  /** Caller-supplied cancellation, honoured alongside the timeout. */
  signal?: AbortSignal;
  timeoutMs?: number;
  headers?: Record<string, string>;
}

export function buildUrl(path: string, baseUrl: string = config.apiBaseUrl): string {
  // An absolute URL (a pagination `next` link) is used as given.
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  // Strip a leading slash so a caller writing '/health/' and one writing
  // 'health/' both resolve against the base URL rather than the domain root.
  const relative = path.startsWith('/') ? path.slice(1) : path;
  return new URL(relative, baseUrl).toString();
}

function isErrorEnvelope(payload: unknown): payload is ApiErrorEnvelope {
  if (typeof payload !== 'object' || payload === null) {
    return false;
  }
  const envelope = (payload as { error?: unknown }).error;
  return (
    typeof envelope === 'object'
    && envelope !== null
    && typeof (envelope as { code?: unknown }).code === 'string'
  );
}

/**
 * Turn a non-OK response into an ApiError, using the envelope when present.
 *
 * A non-JSON error body - an HTML 502 from a proxy, an empty 413 from a load
 * balancer - falls through to a generic message. Its content is never shown
 * to the user: it is not written for them, and may describe the server.
 */
async function toApiError(response: Response): Promise<ApiError> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // Not JSON. The status code is all we can honestly report.
  }

  if (isErrorEnvelope(payload)) {
    return new ApiError(payload.error.message || 'The request failed.', {
      status: response.status,
      code: payload.error.code,
      details: payload.error.details ?? null,
    });
  }

  return new ApiError(`The request failed with status ${response.status}.`, {
    status: response.status,
    code: 'unexpected_response',
  });
}

/**
 * Perform an API request.
 *
 * @returns The parsed JSON body, or null for 204.
 * @throws {ApiError} for every failure - network, timeout, HTTP status, or a
 *   2xx body that is not JSON.
 */
export async function apiRequest<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    method = 'GET',
    body,
    formData,
    signal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    headers = {},
  } = options;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // Honour a caller's signal as well as our timeout, so a screen unmounting
  // cancels the request immediately.
  if (signal) {
    if (signal.aborted) {
      controller.abort();
    } else {
      signal.addEventListener('abort', () => controller.abort(), { once: true });
    }
  }

  const requestHeaders: Record<string, string> = { Accept: 'application/json', ...headers };
  let requestBody: BodyInit | undefined;

  if (formData) {
    requestBody = formData;
  } else if (body !== undefined) {
    requestHeaders['Content-Type'] = 'application/json';
    requestBody = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path), {
      method,
      headers: requestHeaders,
      body: requestBody,
      signal: controller.signal,
    });
  } catch (cause) {
    // fetch rejects for no network, DNS failure, TLS failure and abort alike,
    // and does not reliably say which. The message stays general rather than
    // guessing and misleading whoever is debugging.
    const aborted = (cause as { name?: string } | null)?.name === 'AbortError';
    throw new ApiError(
      aborted
        ? 'The request timed out or was cancelled.'
        : 'Unable to connect to the analysis server.',
      { status: 0, code: aborted ? 'timeout' : 'network_error' },
    );
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    throw await toApiError(response);
  }

  if (response.status === 204) {
    return null as T;
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError('The server returned a response that could not be read.', {
      status: response.status,
      code: 'invalid_json',
    });
  }
}

export const apiClient = {
  get: <T = unknown>(path: string, options?: Omit<RequestOptions, 'method' | 'body' | 'formData'>) =>
    apiRequest<T>(path, { ...options, method: 'GET' }),
  post: <T = unknown>(path: string, body: unknown, options?: Omit<RequestOptions, 'method' | 'body' | 'formData'>) =>
    apiRequest<T>(path, { ...options, method: 'POST', body }),
  upload: <T = unknown>(path: string, formData: FormData, options?: Omit<RequestOptions, 'method' | 'body' | 'formData'>) =>
    apiRequest<T>(path, { ...options, method: 'POST', formData }),
};
