/**
 * What the user is told for each way a request can fail.
 */

import { describeError, logError, OFFLINE_MESSAGE } from './errors';
import { ApiError } from '../api/client';
import { config } from '../config/env';

describe('describeError', () => {
  it('says the server could not be reached when there is no network', () => {
    const described = describeError(new ApiError('Unable to connect to the analysis server.', { status: 0, code: 'network_error' }));

    expect(described.message).toContain(OFFLINE_MESSAGE);
    expect(described.retryable).toBe(true);
  });

  it('names the host that was tried, so a wrong address does not look like no signal', () => {
    const described = describeError(new ApiError('x', { status: 0, code: 'network_error' }));

    expect(described.message).toContain(`configured to use ${new URL(config.apiBaseUrl).host}`);
  });

  it('describes a timeout as taking too long, and retryable', () => {
    const described = describeError(new ApiError('timed out', { status: 0, code: 'timeout' }));

    expect(described.title).toMatch(/too long/i);
    expect(described.retryable).toBe(true);
  });

  it('shows the backend\'s own message for a rejected photo', () => {
    const described = describeError(
      new ApiError('The submitted data was not valid.', {
        status: 400,
        code: 'validation_error',
        details: { image: ['Image is too large. Maximum size is 10 MB.'] },
      }),
    );

    expect(described.message).toContain('Image is too large. Maximum size is 10 MB.');
    expect(described.retryable).toBe(false);
  });

  it('shows the backend\'s message for an unknown product category', () => {
    const described = describeError(
      new ApiError('The submitted data was not valid.', {
        status: 400,
        code: 'validation_error',
        details: { category_code: ["No active product category with code 'foood'."] },
      }),
    );

    expect(described.message).toContain("No active product category with code 'foood'.");
  });

  it.each([
    [401, /sign in/i],
    [403, /permission/i],
    [404, /not found/i],
    [413, /too large/i],
    [500, /server/i],
    [502, /server/i],
    [503, /server/i],
  ])('has a plain message for HTTP %s', (status, pattern) => {
    const described = describeError(new ApiError('x', { status, code: 'whatever' }));
    expect(`${described.title} ${described.message}`).toMatch(pattern);
  });

  it('tells the user how long to wait when throttled', () => {
    const described = describeError(
      new ApiError('Request was throttled.', { status: 429, code: 'rate_limited', details: { retry_after_seconds: 37 } }),
    );

    expect(described.message).toContain('37 seconds');
    expect(described.retryable).toBe(true);
  });

  it('never surfaces server internals from a non-envelope body', () => {
    const described = describeError(
      new ApiError('The request failed with status 500.', { status: 500, code: 'unexpected_response' }),
    );

    expect(described.message).not.toMatch(/traceback|django|exception|status 500/i);
  });

  it('describes a malformed response', () => {
    const described = describeError(new ApiError('bad json', { status: 200, code: 'invalid_json' }));
    expect(described.title).toMatch(/unexpected response/i);
    expect(described.retryable).toBe(true);
  });

  it('handles something that is not an ApiError at all', () => {
    const described = describeError(new TypeError("Cannot read properties of undefined (reading 'x')"));

    expect(described.title).toBe('Something went wrong');
    expect(described.message).not.toContain('undefined');
    expect(described.retryable).toBe(true);
  });
});

describe('logError', () => {
  it('logs the code, status and the underlying cause, never a body', () => {
    const warn = console.warn as jest.Mock;
    const cause = new Error('Unsupported FormDataPart implementation');

    logError('extraction', new ApiError('Unable to connect to the analysis server.', { status: 0, code: 'network_error', cause }));

    expect(warn).toHaveBeenCalledWith(
      '[extraction] network_error (HTTP 0): Unable to connect to the analysis server. <- Error: Unsupported FormDataPart implementation',
    );
  });
});
