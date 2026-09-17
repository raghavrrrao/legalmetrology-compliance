/**
 * Turn a failure into something a person can act on.
 *
 * Every screen that shows an error goes through `describeError`, so the words
 * a user sees for "no network" or "too many requests" are the same everywhere
 * and are decided in one place. The backend's own `message` is used where the
 * API documents it as safe to display (a validation message about the photo);
 * everything else is written here. Nothing from a response body that is not
 * the documented envelope ever reaches the screen - an HTML 502 page or a
 * proxy's 413 body is not written for the user and may describe the server.
 *
 * `logError` is the only place technical detail goes, and only in a
 * development build: the code, the status and the message. Never a request
 * body (it is a photograph), never a header, never a token.
 */

import { ApiError } from '../api/client';
import { config, describeApiTarget } from '../config/env';

export interface UserFacingError {
  /** One short line. */
  title: string;
  /** What happened and what to do, in plain words. */
  message: string;
  /** Whether trying the same request again could reasonably succeed. */
  retryable: boolean;
}

/** The message shown whenever the server could not be reached at all. */
export const OFFLINE_MESSAGE = 'Unable to connect to the analysis server.';

function firstDetailMessage(details: unknown): string | null {
  // Validation details are `{field: [messages]}`. The first message for the
  // upload field is the one that says what was wrong with the photo.
  if (!details || typeof details !== 'object') {
    return null;
  }
  const record = details as Record<string, unknown>;
  for (const key of ['image', 'category_code', 'view_type', 'extraction_run_id']) {
    const value = record[key];
    if (Array.isArray(value) && typeof value[0] === 'string') {
      return value[0];
    }
    if (typeof value === 'string') {
      return value;
    }
  }
  const nonField = record.non_field_errors;
  if (Array.isArray(nonField) && typeof nonField[0] === 'string') {
    return nonField[0];
  }
  return null;
}

function retryAfterSeconds(details: unknown): number | null {
  if (!details || typeof details !== 'object') {
    return null;
  }
  const value = (details as { retry_after_seconds?: unknown }).retry_after_seconds;
  return typeof value === 'number' && value > 0 ? value : null;
}

export function describeError(error: unknown): UserFacingError {
  if (!(error instanceof ApiError)) {
    return {
      title: 'Something went wrong',
      message: 'The app hit an unexpected problem. Please try again.',
      retryable: true,
    };
  }

  if (error.isNetworkError) {
    if (error.code === 'timeout') {
      return {
        title: 'The server took too long',
        message:
          'The analysis did not finish in time. This can happen on a slow connection '
          + 'or with a very large photo. Please try again.',
        retryable: true,
      };
    }
    // Name the host that was tried. A development build pointed at a laptop
    // that is not running the backend looks exactly like a phone with no
    // signal otherwise, and the two have different fixes.
    const { host } = describeApiTarget(config.apiBaseUrl);
    return {
      title: 'No connection',
      message:
        `${OFFLINE_MESSAGE} The app is configured to use ${host}. `
        + 'Check your internet connection and that the server address is right, then try again.',
      retryable: true,
    };
  }

  switch (error.status) {
    case 400: {
      const detail = firstDetailMessage(error.details);
      return {
        title: 'The photo was not accepted',
        message: detail
          ? `${detail} Please try another photo.`
          : 'The server could not accept this request. Please try another photo.',
        retryable: false,
      };
    }
    case 401:
      return {
        title: 'Sign-in required',
        message:
          'This server requires you to sign in before analysing a label. '
          + 'The mobile app does not support sign-in yet.',
        retryable: false,
      };
    case 403:
      return {
        title: 'Not allowed',
        message: 'You do not have permission to use the analysis service on this server.',
        retryable: false,
      };
    case 404:
      return {
        title: 'Not found',
        message:
          'The analysis service was not found at the configured address, or this '
          + 'result is no longer available.',
        retryable: false,
      };
    case 413:
      return {
        title: 'Photo too large',
        message: 'The server refused the photo because it is too large. Please take a smaller photo.',
        retryable: false,
      };
    case 429: {
      const wait = retryAfterSeconds(error.details);
      return {
        title: 'Too many requests',
        message: wait
          ? `The server is limiting requests. Please wait about ${wait} seconds and try again.`
          : 'The server is limiting requests. Please wait a moment and try again.',
        retryable: true,
      };
    }
    default:
      break;
  }

  if (error.status >= 500) {
    return {
      title: 'Server problem',
      message: 'The analysis server had a problem processing this request. Please try again in a moment.',
      retryable: true,
    };
  }

  if (error.code === 'invalid_json' || error.code === 'unexpected_response') {
    return {
      title: 'Unexpected response',
      message: 'The server sent a response the app could not understand. Please try again.',
      retryable: true,
    };
  }

  return {
    title: 'Request failed',
    message: error.message || 'The request failed. Please try again.',
    retryable: true,
  };
}

/**
 * Record technical detail for a developer, safely.
 *
 * Development builds only. Logs the stable code, the HTTP status and the
 * message - enough to tell a timeout from a 500 from a bad URL - and nothing
 * else. Photographs, headers and tokens are never logged; nor is anything
 * from a response body beyond the envelope's `code`.
 */
export function logError(context: string, error: unknown): void {
  if (!config.isDevelopment) {
    return;
  }
  if (error instanceof ApiError) {
    // The underlying error is the useful part of a status-0 failure: it is
    // what separates "no route to host" from "fetch could not encode the
    // body" - both of which the user sees as "unable to connect".
    const cause = error.cause instanceof Error ? ` <- ${error.cause.name}: ${error.cause.message}` : '';
    console.warn(`[${context}] ${error.code} (HTTP ${error.status}): ${error.message}${cause}`);
    return;
  }
  const message = error instanceof Error ? error.message : String(error);
  console.warn(`[${context}] ${message}`);
}
