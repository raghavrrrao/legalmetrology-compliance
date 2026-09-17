/**
 * API client behaviour.
 *
 * `fetch` is stubbed so these run without a backend, but the assertions are
 * about real contracts: the error envelope, URL joining, timeouts, and what is
 * (and is not) sent with a multipart body.
 */

import { ApiError, apiClient, apiRequest, buildUrl } from './client';
import { errorEnvelope, jsonResponse } from '../../tests/fixtures';

const fetchMock = jest.fn();

beforeEach(() => {
  (globalThis as unknown as { fetch: unknown }).fetch = fetchMock;
});

describe('URL construction', () => {
  it('resolves a relative path against the configured base', () => {
    expect(buildUrl('extraction/', 'http://api.test/api/v1/')).toBe('http://api.test/api/v1/extraction/');
  });

  it('resolves a leading-slash path against the base, not the domain root', () => {
    expect(buildUrl('/compliance/', 'http://api.test/api/v1/')).toBe('http://api.test/api/v1/compliance/');
  });

  it('passes an absolute URL through unchanged', () => {
    expect(buildUrl('https://api.test/api/v1/compliance/?page=2', 'http://other/api/v1/')).toBe(
      'https://api.test/api/v1/compliance/?page=2',
    );
  });

  it('sends requests to the configured base', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await apiRequest('health/');

    const [url] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/health\/$/);
  });
});

describe('successful requests', () => {
  it('returns the parsed body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));
    await expect(apiRequest('health/')).resolves.toEqual({ status: 'ok' });
  });

  it('returns null for 204', async () => {
    fetchMock.mockResolvedValue(jsonResponse(null, { status: 204 }));
    await expect(apiRequest('thing/')).resolves.toBeNull();
  });

  it('serialises a JSON body and says so', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));

    await apiClient.post('compliance/', { extraction_run_id: 'abc' });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe('POST');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(init.headers.Accept).toBe('application/json');
    expect(JSON.parse(init.body)).toEqual({ extraction_run_id: 'abc' });
  });

  it('sends no credentials header and no token', async () => {
    // The analysis endpoints are reached anonymously under the backend's demo
    // switch. Nothing must be attached that pretends otherwise.
    fetchMock.mockResolvedValue(jsonResponse({}));

    await apiRequest('health/');

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBeUndefined();
    expect(init.headers.Cookie).toBeUndefined();
    expect(init.headers['X-CSRFToken']).toBeUndefined();
  });
});

describe('uploads', () => {
  it('sends the FormData as the body without setting Content-Type', async () => {
    // The runtime must add the multipart boundary itself; setting the header
    // manually produces a request Django cannot parse.
    fetchMock.mockResolvedValue(jsonResponse({}));
    const formData = new FormData();

    await apiClient.upload('extraction/', formData);

    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe('POST');
    expect(init.body).toBe(formData);
    expect(init.headers['Content-Type']).toBeUndefined();
  });
});

describe('error envelope', () => {
  it('surfaces the backend code, message and details on a 400', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        errorEnvelope('validation_error', 'The submitted data was not valid.', {
          image: ['Image is too large. Maximum size is 10 MB.'],
        }),
        { status: 400 },
      ),
    );

    await expect(apiRequest('extraction/')).rejects.toMatchObject({
      name: 'ApiError',
      status: 400,
      code: 'validation_error',
      message: 'The submitted data was not valid.',
      details: { image: ['Image is too large. Maximum size is 10 MB.'] },
    });
  });

  it.each([
    [401, 'not_authenticated'],
    [403, 'permission_denied'],
    [404, 'not_found'],
    [429, 'rate_limited'],
  ])('carries the status and code for %s', async (status, code) => {
    fetchMock.mockResolvedValue(jsonResponse(errorEnvelope(code, 'Nope.'), { status }));

    const error = await apiRequest('compliance/').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(status);
    expect((error as ApiError).code).toBe(code);
    expect((error as ApiError).isNetworkError).toBe(false);
  });

  it('keeps retry_after_seconds from a 429', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(errorEnvelope('rate_limited', 'Request was throttled.', { retry_after_seconds: 42 }), {
        status: 429,
      }),
    );

    const error = (await apiRequest('extraction/').catch((e: unknown) => e)) as ApiError;

    expect(error.details).toEqual({ retry_after_seconds: 42 });
  });

  it('handles an error body that is not JSON without leaking it', async () => {
    // An HTML 502 from a proxy, or an empty 413 from a load balancer.
    fetchMock.mockResolvedValue({
      ok: false,
      status: 413,
      json: async () => {
        throw new Error('<html>Request Entity Too Large</html>');
      },
    });

    const error = (await apiRequest('extraction/').catch((e: unknown) => e)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(413);
    expect(error.code).toBe('unexpected_response');
    expect(error.message).not.toContain('html');
  });

  it('treats a 500 with the generic body as a server error', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Server Error (500)' }, { status: 500 }));

    const error = (await apiRequest('compliance/').catch((e: unknown) => e)) as ApiError;

    expect(error.status).toBe(500);
    expect(error.code).toBe('unexpected_response');
  });

  it('reports a 2xx body that is not JSON', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError('Unexpected token <');
      },
    });

    const error = (await apiRequest('health/').catch((e: unknown) => e)) as ApiError;

    expect(error.code).toBe('invalid_json');
    expect(error.status).toBe(200);
  });
});

describe('network failures', () => {
  it('reports a network failure distinctly from a server error', async () => {
    fetchMock.mockRejectedValue(new TypeError('Network request failed'));

    const error = (await apiRequest('health/').catch((e: unknown) => e)) as ApiError;

    expect(error.isNetworkError).toBe(true);
    expect(error.status).toBe(0);
    expect(error.code).toBe('network_error');
    expect(error.message).toBe('Unable to connect to the analysis server.');
  });

  it('keeps the underlying error as the cause, for development logs', async () => {
    // expo/fetch rejects before any request when it cannot encode the body.
    // The user still sees "unable to connect"; the log must say why.
    fetchMock.mockRejectedValue(new Error('Unsupported FormDataPart implementation'));

    const error = (await apiRequest('extraction/', { method: 'POST', formData: new FormData() }).catch((e: unknown) => e)) as ApiError;

    expect(error.code).toBe('network_error');
    expect(error.status).toBe(0);
    expect(error.cause).toEqual(expect.objectContaining({ message: 'Unsupported FormDataPart implementation' }));
    expect(error.message).not.toContain('FormDataPart');
  });

  it('reports an abort as a timeout', async () => {
    const abort = new Error('Aborted');
    abort.name = 'AbortError';
    fetchMock.mockRejectedValue(abort);

    const error = (await apiRequest('health/').catch((e: unknown) => e)) as ApiError;

    expect(error.code).toBe('timeout');
    expect(error.isNetworkError).toBe(true);
  });

  it("classifies our own timeout as a timeout even when fetch calls it a cancellation", async () => {
    // expo/fetch rejects an aborted request with a FetchError whose name is
    // "Error" and whose message is "fetch failed: Fetch request has been
    // canceled" - not an AbortError.
    jest.useFakeTimers();
    try {
      fetchMock.mockImplementation(
        (_url: string, init: { signal: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            init.signal.addEventListener('abort', () => {
              reject(new Error('fetch failed: Fetch request has been canceled'));
            });
          }),
      );

      const pending = apiRequest('health/', { timeoutMs: 1000 });
      jest.advanceTimersByTime(1001);

      const error = (await pending.catch((e: unknown) => e)) as ApiError;
      expect(error.code).toBe('timeout');
      expect(error.cause).toEqual(expect.objectContaining({ message: 'fetch failed: Fetch request has been canceled' }));
    } finally {
      jest.useRealTimers();
    }
  });

  it('aborts the request when the timeout elapses', async () => {
    jest.useFakeTimers();
    try {
      fetchMock.mockImplementation(
        (_url: string, init: { signal: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            init.signal.addEventListener('abort', () => {
              const error = new Error('Aborted');
              error.name = 'AbortError';
              reject(error);
            });
          }),
      );

      const pending = apiRequest('extraction/', { timeoutMs: 1000 });
      jest.advanceTimersByTime(1001);

      await expect(pending).rejects.toMatchObject({ code: 'timeout' });
    } finally {
      jest.useRealTimers();
    }
  });

  it('honours a caller-supplied abort signal', async () => {
    fetchMock.mockImplementation(
      (_url: string, init: { signal: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          init.signal.addEventListener('abort', () => {
            const error = new Error('Aborted');
            error.name = 'AbortError';
            reject(error);
          });
        }),
    );
    const controller = new AbortController();

    const pending = apiRequest('extraction/', { signal: controller.signal });
    controller.abort();

    await expect(pending).rejects.toMatchObject({ code: 'timeout' });
  });
});
