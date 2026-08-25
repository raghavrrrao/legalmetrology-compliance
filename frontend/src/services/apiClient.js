/**
 * The single HTTP client for talking to the Django REST API.
 *
 * Every request in the app goes through here. That gives one place to handle
 * the API's error envelope, CSRF, credentials and timeouts - rather than
 * thirteen slightly different `fetch` calls written by six people.
 *
 * The backend returns errors in a fixed shape (see docs/api.md):
 *
 *     { "error": { "code": "...", "message": "...", "details": ... } }
 *
 * `ApiError` below carries that through unchanged, so a component can branch
 * on `error.code` instead of matching on English text.
 */

import { config } from '../config/env.js';

/** Requests that take longer than this are aborted. */
const DEFAULT_TIMEOUT_MS = 15000;

/**
 * An API request that failed, with the backend's structured error attached.
 *
 * `code` is stable and safe to branch on. `message` is safe to display.
 * `status` is 0 when the request never reached the server (network down,
 * CORS rejected, timeout) - which is a different problem from a 500 and the
 * UI should say so.
 */
export class ApiError extends Error {
  constructor(message, { status = 0, code = 'network_error', details = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** True when the request never got an answer from the server. */
  get isNetworkError() {
    return this.status === 0;
  }
}

/**
 * Read Django's CSRF cookie.
 *
 * Needed for unsafe methods once session authentication is in use. Returns
 * null when the cookie is absent, which is the normal state before login.
 */
function readCsrfToken() {
  if (typeof document === 'undefined') {
    return null;
  }
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function buildUrl(path) {
  // Strip a leading slash so a caller writing '/health/' and one writing
  // 'health/' both resolve against the base URL rather than the domain root.
  const relative = path.startsWith('/') ? path.slice(1) : path;
  return new URL(relative, config.apiBaseUrl).toString();
}

/**
 * Turn a non-OK response into an ApiError, using the envelope when present.
 */
async function toApiError(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // A non-JSON error body (an HTML 500 page, an empty 502 from a proxy).
    // Fall through to the generic message below rather than throwing here.
  }

  const envelope = payload?.error;
  if (envelope?.code) {
    return new ApiError(envelope.message || 'The request failed.', {
      status: response.status,
      code: envelope.code,
      details: envelope.details ?? null,
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
 * @param {string} path      Path relative to the API base URL, e.g. 'health/'.
 * @param {object} [options]
 * @param {string} [options.method='GET']
 * @param {object} [options.body]     JSON-serialised automatically.
 * @param {FormData} [options.formData] For file uploads. Do NOT set
 *        Content-Type yourself - the browser must add the multipart boundary.
 * @param {AbortSignal} [options.signal] Caller-supplied cancellation.
 * @param {number} [options.timeoutMs]
 * @returns {Promise<any>} The parsed JSON body, or null for 204.
 * @throws {ApiError}
 */
export async function apiRequest(path, options = {}) {
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

  // Honour a caller's signal as well as our timeout, so a component
  // unmounting cancels the request immediately.
  if (signal) {
    signal.addEventListener('abort', () => controller.abort(), { once: true });
  }

  const requestHeaders = { Accept: 'application/json', ...headers };
  let requestBody;

  if (formData) {
    requestBody = formData;
  } else if (body !== undefined) {
    requestHeaders['Content-Type'] = 'application/json';
    requestBody = JSON.stringify(body);
  }

  if (!['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase())) {
    const csrfToken = readCsrfToken();
    if (csrfToken) {
      requestHeaders['X-CSRFToken'] = csrfToken;
    }
  }

  let response;
  try {
    response = await fetch(buildUrl(path), {
      method,
      headers: requestHeaders,
      body: requestBody,
      // Sends the session cookie cross-origin. The backend allows this for
      // the configured origins only (CORS_ALLOW_CREDENTIALS).
      credentials: 'include',
      signal: controller.signal,
    });
  } catch (cause) {
    // fetch rejects for network failure, CORS rejection and abort alike. The
    // browser deliberately does not say which, so the message stays general
    // rather than guessing and misleading whoever is debugging.
    const aborted = cause?.name === 'AbortError';
    throw new ApiError(
      aborted
        ? 'The request timed out or was cancelled.'
        : 'Could not reach the server. Check that the backend is running.',
      { status: 0, code: aborted ? 'timeout' : 'network_error' },
    );
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    throw await toApiError(response);
  }

  if (response.status === 204) {
    return null;
  }

  try {
    return await response.json();
  } catch {
    throw new ApiError('The server returned a response that was not valid JSON.', {
      status: response.status,
      code: 'invalid_json',
    });
  }
}

export const apiClient = {
  get: (path, options) => apiRequest(path, { ...options, method: 'GET' }),
  post: (path, body, options) => apiRequest(path, { ...options, method: 'POST', body }),
  upload: (path, formData, options) =>
    apiRequest(path, { ...options, method: 'POST', formData }),
};
