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

/**
 * Resolve the API base URL for the build that is actually running.
 *
 * The localhost default is a development convenience and nothing more. A
 * production bundle that fell back to it would ship a site asking every
 * visitor's own machine for the API - a failure that looks like the backend
 * being down, on a machine the operator cannot see. So production refuses to
 * start without an explicit value instead of guessing one.
 *
 * `frontend/.env.production` supplies that value for the deployed backend, and
 * `vite.config.js` refuses to produce a bundle without it, so reaching this
 * throw means the variable was explicitly blanked at build time.
 *
 * @param {string|undefined} value  The raw VITE_API_BASE_URL.
 * @param {boolean} isProduction    import.meta.env.PROD.
 */
function resolveApiBaseUrl(value, isProduction) {
  if ((value ?? '').trim()) {
    return normaliseBaseUrl(value);
  }

  if (isProduction) {
    throw new Error(
      'VITE_API_BASE_URL is not set. A production build must be given the '
        + 'deployed API URL (including the /api/v1/ prefix) at build time; '
        + 'falling back to http://localhost:8000 would point the deployed site '
        + "at each visitor's own computer. See frontend/.env.example and "
        + 'docs/deployment.md.',
    );
  }

  return DEFAULT_API_BASE_URL;
}

export const config = Object.freeze({
  /** Base URL of the Django REST API, always with a trailing slash. */
  apiBaseUrl: resolveApiBaseUrl(
    import.meta.env?.VITE_API_BASE_URL,
    import.meta.env?.PROD ?? false,
  ),

  /** True during `vite dev`. Use for developer affordances, never for auth. */
  isDevelopment: import.meta.env?.DEV ?? false,
});

export { normaliseBaseUrl, resolveApiBaseUrl, DEFAULT_API_BASE_URL };
