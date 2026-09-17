/**
 * The server check the home screen shows, over a stubbed `fetch`.
 */

import { act, renderHook, waitFor } from '@testing-library/react-native';

import { useApiHealth } from './useApiHealth';
import { errorEnvelope, jsonResponse } from '../../tests/fixtures';
import { config } from '../config/env';

const fetchMock = jest.fn();

beforeEach(() => {
  (globalThis as unknown as { fetch: unknown }).fetch = fetchMock;
  jest.spyOn(console, 'info').mockImplementation(() => undefined);
});

const healthBody = {
  status: 'ok',
  api_version: 'v1',
  extraction_engine: { name: 'tesseract', version: '0.3.0', is_placeholder: false },
};

describe('useApiHealth', () => {
  it('asks health/ through the same client and reports the engine', async () => {
    fetchMock.mockResolvedValue(jsonResponse(healthBody));

    const { result } = await renderHook(() => useApiHealth());

    await waitFor(() => expect(result.current.phase).toBe('ok'));
    expect(fetchMock.mock.calls[0][0]).toBe(`${config.apiBaseUrl}health/`);
    expect(fetchMock.mock.calls[0][1].method).toBe('GET');
    if (result.current.phase === 'ok') {
      expect(result.current.health.extractionEngine).toEqual({ name: 'tesseract', version: '0.3.0', isPlaceholder: false });
    }
    expect(result.current.target).toEqual({
      origin: new URL(config.apiBaseUrl).origin,
      host: new URL(config.apiBaseUrl).host,
      path: '/api/v1/',
      https: config.apiBaseUrl.startsWith('https:'),
    });
  });

  it('reports the server as unreachable when the request fails, and can check again', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network request failed')).mockResolvedValueOnce(jsonResponse(healthBody));

    const { result } = await renderHook(() => useApiHealth());

    await waitFor(() => expect(result.current.phase).toBe('unreachable'));

    // `check` sets state synchronously (back to "checking"), so it is a
    // state update the test must perform inside act.
    await act(async () => {
      result.current.check();
    });
    await waitFor(() => expect(result.current.phase).toBe('ok'));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('treats an HTTP error as unreachable too', async () => {
    fetchMock.mockResolvedValue(jsonResponse(errorEnvelope('not_found', 'Not found.'), { status: 404 }));

    const { result } = await renderHook(() => useApiHealth());

    await waitFor(() => expect(result.current.phase).toBe('unreachable'));
  });

  it('logs only where requests go, in development', async () => {
    fetchMock.mockResolvedValue(jsonResponse(healthBody));

    await renderHook(() => useApiHealth());

    const calls = (console.info as jest.Mock).mock.calls.map((call) => String(call[0]));
    for (const line of calls) {
      expect(line).toMatch(/^\[api\] target http/);
      expect(line).not.toMatch(/token|secret|key/i);
    }
  });
});
