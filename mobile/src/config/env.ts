/**
 * The single source of truth for mobile configuration.
 *
 * No screen or component reads `process.env` directly. Everything goes through
 * here, so there is exactly one place to look when the API URL is wrong and
 * exactly one place to change when it moves - the same rule the web client
 * follows in `frontend/src/config/env.js`.
 *
 * SECURITY: every `EXPO_PUBLIC_`-prefixed variable is inlined into the
 * JavaScript bundle at build time and is readable by anyone who unpacks the
 * app. Nothing secret may be read here. See mobile/.env.example.
 */

import Constants from 'expo-constants';

/** Where the backend listens in development, relative to the dev machine. */
export const DEFAULT_API_PORT = 8000;
export const DEFAULT_API_PATH = '/api/v1/';
export const DEFAULT_API_BASE_URL = `http://localhost:${DEFAULT_API_PORT}${DEFAULT_API_PATH}`;

/**
 * Largest photograph the client will attempt to upload, in megabytes.
 *
 * Mirrors the backend's default `MAX_IMAGE_UPLOAD_SIZE_MB` so the user gets an
 * immediate message instead of waiting for a 400. The backend remains the
 * authority: if its limit is lower the upload is still rejected there, and
 * this number never makes an oversized upload acceptable.
 */
export const MAX_UPLOAD_SIZE_MB = 10;
export const MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024;

/**
 * Most photographs one inspection may carry.
 *
 * Mirrors the backend's `MAX_IMAGES_PER_INSPECTION`
 * (`backend/apps/images/constants.py`) so the user is stopped while they are
 * choosing rather than after a multi-megabyte upload. The backend remains the
 * authority: if its limit is lower the request is still rejected there, and
 * this number never makes an over-long set acceptable.
 *
 * Six covers front, back, two side panels, a bottom label and a close-up. It
 * is not derived from the Rules, which say nothing about how many photographs
 * anybody takes.
 */
export const MAX_INSPECTION_IMAGES = 6;

/**
 * Normalise a base URL to exactly one trailing slash.
 *
 * Without this, `${base}health/` produces either a double slash or a missing
 * one depending on how somebody typed the .env value - and Django's
 * APPEND_SLASH redirect turns a wrong slash into a silently-converted request.
 */
export function normaliseBaseUrl(value: string | undefined | null): string {
  const trimmed = (value ?? '').trim();
  if (!trimmed) {
    return DEFAULT_API_BASE_URL;
  }
  return trimmed.endsWith('/') ? trimmed : `${trimmed}/`;
}

/**
 * Derive a development API URL from where Metro is being served from.
 *
 * `localhost` on a phone is the phone. The one machine a development build
 * already knows how to reach is the one serving its JavaScript, and Expo
 * exposes that as `hostUri` ("192.168.1.20:8081"). Pointing at the same host
 * on the backend's port is the honest default for a physical device, and it
 * also works for the Android emulator when Metro reports the LAN address.
 *
 * Returns null when there is no host to derive from - a production build, or
 * a test - so the caller falls back to the localhost default.
 */
export function apiBaseUrlFromMetroHost(hostUri: string | undefined | null): string | null {
  if (!hostUri) {
    return null;
  }
  // "192.168.1.20:8081" or "192.168.1.20:8081/--/..."; keep only the host.
  const host = hostUri.split('/')[0].split(':')[0].trim();
  if (!host) {
    return null;
  }
  return `http://${host}:${DEFAULT_API_PORT}${DEFAULT_API_PATH}`;
}

/**
 * Resolve the API base URL for the build that is actually running.
 *
 * Which value arrives here is decided by Expo's env-file precedence, and
 * `expo start` never reads `.env.production`:
 *
 *     shell variable  >  .env.local (git-ignored: a local backend)
 *                     >  .env.development (committed: Railway)   [expo start]
 *                     >  .env.production  (committed: Railway)   [export / EAS]
 *
 * The derived and localhost defaults below are reached only when every file
 * leaves the variable empty. They are development conveniences and nothing
 * more. A production app that fell back to either would ask the user's own
 * phone for the API - a failure that looks like the backend being down, on a
 * device the operator cannot see. So a production build refuses to start
 * without an explicit value instead of guessing one; `mobile/.env.production`
 * supplies that value for the deployed backend.
 *
 * @param value          The raw EXPO_PUBLIC_API_BASE_URL.
 * @param isDevelopment  React Native's `__DEV__`.
 * @param metroHostUri   `Constants.expoConfig.hostUri`, when running from Metro.
 */
export function resolveApiBaseUrl(
  value: string | undefined | null,
  isDevelopment: boolean,
  metroHostUri?: string | null,
): string {
  if ((value ?? '').trim()) {
    return normaliseBaseUrl(value);
  }

  if (!isDevelopment) {
    throw new Error(
      'EXPO_PUBLIC_API_BASE_URL is not set. A production build must be given '
        + 'the deployed API URL (including the /api/v1/ prefix) at build time; '
        + "falling back to localhost would point the app at the user's own "
        + 'phone. See mobile/.env.example and docs/mobile.md.',
    );
  }

  return apiBaseUrlFromMetroHost(metroHostUri) ?? DEFAULT_API_BASE_URL;
}

declare const __DEV__: boolean;

/**
 * The API target in the terms a person debugging connectivity needs: where
 * requests go and whether they are encrypted. Contains no secret - the base
 * URL is public configuration - and is what the app shows and logs when the
 * server cannot be reached, so "unable to connect" always names the host that
 * was tried.
 */
export function describeApiTarget(baseUrl: string): { origin: string; host: string; path: string; https: boolean } {
  const url = new URL(baseUrl);
  return { origin: url.origin, host: url.host, path: url.pathname, https: url.protocol === 'https:' };
}

export const config = Object.freeze({
  /** Base URL of the Django REST API, always with a trailing slash. */
  apiBaseUrl: resolveApiBaseUrl(
    // Accessed by its full name on purpose: Expo replaces this exact expression
    // at bundle time, and `process.env[name]` would not be replaced.
    process.env.EXPO_PUBLIC_API_BASE_URL,
    typeof __DEV__ === 'boolean' ? __DEV__ : true,
    Constants.expoConfig?.hostUri,
  ),

  /** True in a development build. Use for developer affordances, never for auth. */
  isDevelopment: typeof __DEV__ === 'boolean' ? __DEV__ : true,

  /**
   * Whether the base URL was set explicitly (EXPO_PUBLIC_API_BASE_URL, from
   * whichever env file or shell variable won) or guessed from the Metro host.
   * Shown on the home screen and in the development log so a build that is
   * talking to the wrong server says so, instead of looking offline.
   */
  apiBaseUrlSource: (process.env.EXPO_PUBLIC_API_BASE_URL ?? '').trim() ? ('configured' as const) : ('development-default' as const),
});
