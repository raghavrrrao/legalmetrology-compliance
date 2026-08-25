/**
 * The health-loading hook.
 *
 * `refresh` matters more than it looks: the error UI tells a user to start
 * Django and then press "Try again", so if refresh did not re-issue the
 * request, the app would be permanently stuck on an error that the user had
 * already fixed. These tests pin the recovery path.
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useApiHealth } from './useApiHealth.js';

function healthBody() {
  return {
    status: 'ok',
    api_version: 'v1',
    dependencies: { database: 'ok', extraction_engine: 'ok' },
    extraction_engine: { name: 'null-engine', version: '0.1.0', is_placeholder: true },
    compliance_rules: { active_total: 0, verified: 0, unverified: 0 },
  };
}

function okResponse() {
  return { ok: true, status: 200, json: async () => healthBody() };
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('initial load', () => {
  it('exposes data once the request resolves', async () => {
    fetch.mockResolvedValue(okResponse());

    const { result } = renderHook(() => useApiHealth());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data.apiVersion).toBe('v1');
    expect(result.current.error).toBeNull();
  });

  it('exposes the error as a value rather than throwing', async () => {
    fetch.mockRejectedValue(new TypeError('Failed to fetch'));

    const { result } = renderHook(() => useApiHealth());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error.code).toBe('network_error');
    expect(result.current.data).toBeNull();
  });
});

describe('refresh', () => {
  it('issues another request', async () => {
    fetch.mockResolvedValue(okResponse());
    const { result } = renderHook(() => useApiHealth());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(fetch).toHaveBeenCalledTimes(1);

    await act(async () => {
      result.current.refresh();
    });

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it('recovers from an error once the backend comes back', async () => {
    // This is the exact flow the error message instructs the user to perform:
    // the first load fails, they start Django, they press "Try again".
    fetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const { result } = renderHook(() => useApiHealth());
    await waitFor(() => expect(result.current.error).not.toBeNull());

    fetch.mockResolvedValue(okResponse());
    await act(async () => {
      result.current.refresh();
    });

    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.data.apiVersion).toBe('v1');
  });

  it('keeps a stable identity so it can be a dependency', async () => {
    fetch.mockResolvedValue(okResponse());
    const { result } = renderHook(() => useApiHealth());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const first = result.current.refresh;
    await act(async () => {
      result.current.refresh();
    });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));

    expect(result.current.refresh).toBe(first);
  });
});

describe('unmount', () => {
  it('aborts the in-flight request', async () => {
    let capturedSignal;
    fetch.mockImplementation((_url, options) => {
      capturedSignal = options.signal;
      return new Promise(() => {}); // never settles
    });

    const { unmount } = renderHook(() => useApiHealth());
    expect(capturedSignal.aborted).toBe(false);

    unmount();

    expect(capturedSignal.aborted).toBe(true);
  });
});
