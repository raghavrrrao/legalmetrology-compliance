/**
 * The single source of truth for frontend configuration.
 *
 * No component reads `import.meta.env` directly. Everything goes through here,
 * so there is exactly one place to look when the API URL is wrong, and exactly
 * one place to change when it moves.
 *
 * SECURITY: every `VITE_`-prefixed variable is inlined into the browser bundle
 * at build time and is publicly readable. Nothing secret may be read here.
 * See frontend/.env.example.
 */

const DEFAULT_API_BASE_URL = 'http://localhost:8000/api/v1/';

/**
 * Normalise a base URL to exactly one trailing slash.
 *
 * Without this, `${base}health/` produces either a double slash or a missing
 * one depending on how somebody typed the .env value - and Django's
 * APPEND_SLASH redirect turns a wrong slash into a silently-converted request.
 */
function normaliseBaseUrl(value) {
  const trimmed = (value ?? '').trim();
  if (!trimmed) {
    return DEFAULT_API_BASE_URL;
  }
  return trimmed.endsWith('/') ? trimmed : `${trimmed}/`;
}

export const config = Object.freeze({
  /** Base URL of the Django REST API, always with a trailing slash. */
  apiBaseUrl: normaliseBaseUrl(import.meta.env?.VITE_API_BASE_URL),

  /** True during `vite dev`. Use for developer affordances, never for auth. */
  isDevelopment: import.meta.env?.DEV ?? false,
});

export { normaliseBaseUrl, DEFAULT_API_BASE_URL };
