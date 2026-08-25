/**
 * API client behaviour.
 *
 * `fetch` is stubbed so these run without a backend, but the assertions are
 * about real contracts: the error envelope, credentials, CSRF and URL joining.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiRequest } from './apiClient.js';
import { DEFAULT_API_BASE_URL, normaliseBaseUrl } from '../config/env.js';

function jsonResponse(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
  document.cookie = '';
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('URL construction', () => {
  it('adds a missing trailing slash to the base URL', () => {
    expect(normaliseBaseUrl('http://x/api/v1')).toBe('http://x/api/v1/');
  });

  it('leaves an existing trailing slash alone', () => {
    expect(normaliseBaseUrl('http://x/api/v1/')).toBe('http://x/api/v1/');
  });

  it('falls back to the default when unset', () => {
    expect(normaliseBaseUrl(undefined)).toBe(DEFAULT_API_BASE_URL);
    expect(normaliseBaseUrl('   ')).toBe(DEFAULT_API_BASE_URL);
  });

  it('resolves a leading-slash path against the base, not the domain root', async () => {
    fetch.mockResolvedValue(jsonResponse({ ok: true }));

    await apiRequest('/health/');

    const [url] = fetch.mock.calls[0];
    expect(url).toContain('/api/v1/health/');
  });
});

describe('successful requests', () => {
  it('returns the parsed body', async () => {
    fetch.mockResolvedValue(jsonResponse({ status: 'ok' }));
    await expect(apiRequest('health/')).resolves.toEqual({ status: 'ok' });
  });

  it('returns null for 204', async () => {
    fetch.mockResolvedValue({ ok: true, status: 204, json: async () => null });
    await expect(apiRequest('thing/')).resolves.toBeNull();
  });

  it('sends credentials so the session cookie travels cross-origin', async () => {
    fetch.mockResolvedValue(jsonResponse({}));

    await apiRequest('health/');

    expect(fetch.mock.calls[0][1].credentials).toBe('include');
  });
});

describe('error envelope', () => {
  it('surfaces the backend code and message', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'validation_error',
            message: 'The submitted data was not valid.',
            details: { image: ['This field is required.'] },
          },
        },
        { status: 400 },
      ),
    );

    await expect(apiRequest('images/')).rejects.toMatchObject({
      name: 'ApiError',
      status: 400,
      code: 'validation_error',
      details: { image: ['This field is required.'] },
    });
  });

  it('handles an error body that is not JSON', async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('not json');
      },
    });

    const error = await apiRequest('health/').catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe('unexpected_response');
    expect(error.status).toBe(502);
  });

  it('reports a network failure distinctly from a server error', async () => {
    fetch.mockRejectedValue(new TypeError('Failed to fetch'));

    const error = await apiRequest('health/').catch((e) => e);

    expect(error.isNetworkError).toBe(true);
    expect(error.code).toBe('network_error');
    expect(error.message).toContain('backend is running');
  });

  it('reports an abort as a timeout', async () => {
    const abort = new Error('aborted');
    abort.name = 'AbortError';
    fetch.mockRejectedValue(abort);

    const error = await apiRequest('health/').catch((e) => e);

    expect(error.code).toBe('timeout');
  });
});

describe('CSRF', () => {
  it('attaches the token to unsafe methods', async () => {
    document.cookie = 'csrftoken=abc123';
    fetch.mockResolvedValue(jsonResponse({}));

    await apiRequest('things/', { method: 'POST', body: { a: 1 } });

    expect(fetch.mock.calls[0][1].headers['X-CSRFToken']).toBe('abc123');
  });

  it('does not attach the token to GET', async () => {
    document.cookie = 'csrftoken=abc123';
    fetch.mockResolvedValue(jsonResponse({}));

    await apiRequest('health/');

    expect(fetch.mock.calls[0][1].headers['X-CSRFToken']).toBeUndefined();
  });
});

describe('uploads', () => {
  it('does not set Content-Type for FormData', async () => {
    // The browser must add the multipart boundary itself; setting the header
    // manually produces a request Django cannot parse.
    fetch.mockResolvedValue(jsonResponse({}));
    const formData = new FormData();

    await apiRequest('images/', { method: 'POST', formData });

    expect(fetch.mock.calls[0][1].headers['Content-Type']).toBeUndefined();
  });
});
