/**
 * API base URL configuration.
 *
 * The contracts: one trailing slash, a development default derived from
 * where Metro is served, and a production build that refuses to guess.
 */

import {
  apiBaseUrlFromMetroHost,
  DEFAULT_API_BASE_URL,
  normaliseBaseUrl,
  resolveApiBaseUrl,
} from './env';

describe('normaliseBaseUrl', () => {
  it('adds a missing trailing slash', () => {
    expect(normaliseBaseUrl('http://x/api/v1')).toBe('http://x/api/v1/');
  });

  it('leaves an existing trailing slash alone', () => {
    expect(normaliseBaseUrl('http://x/api/v1/')).toBe('http://x/api/v1/');
  });

  it('trims whitespace', () => {
    expect(normaliseBaseUrl('  http://x/api/v1/  ')).toBe('http://x/api/v1/');
  });

  it('falls back to the default when unset', () => {
    expect(normaliseBaseUrl(undefined)).toBe(DEFAULT_API_BASE_URL);
    expect(normaliseBaseUrl('   ')).toBe(DEFAULT_API_BASE_URL);
  });
});

describe('apiBaseUrlFromMetroHost', () => {
  it('points at the Metro host on the backend port', () => {
    expect(apiBaseUrlFromMetroHost('192.168.1.20:8081')).toBe('http://192.168.1.20:8000/api/v1/');
  });

  it('ignores anything after the host', () => {
    expect(apiBaseUrlFromMetroHost('192.168.1.20:8081/--/path')).toBe('http://192.168.1.20:8000/api/v1/');
  });

  it('returns null when there is no host to derive from', () => {
    expect(apiBaseUrlFromMetroHost(undefined)).toBeNull();
    expect(apiBaseUrlFromMetroHost('')).toBeNull();
    expect(apiBaseUrlFromMetroHost(':8081')).toBeNull();
  });
});

describe('resolveApiBaseUrl', () => {
  const DEV = true;
  const PROD = false;

  it('uses the configured URL whatever the build', () => {
    expect(resolveApiBaseUrl('https://api.example.test/api/v1', PROD)).toBe('https://api.example.test/api/v1/');
    expect(resolveApiBaseUrl('https://api.example.test/api/v1', DEV, '10.0.0.5:8081')).toBe(
      'https://api.example.test/api/v1/',
    );
  });

  it('derives from the Metro host in development when unset', () => {
    expect(resolveApiBaseUrl(undefined, DEV, '10.0.0.5:8081')).toBe('http://10.0.0.5:8000/api/v1/');
  });

  it('falls back to localhost in development with no Metro host', () => {
    expect(resolveApiBaseUrl(undefined, DEV)).toBe(DEFAULT_API_BASE_URL);
    expect(resolveApiBaseUrl('', DEV, null)).toBe(DEFAULT_API_BASE_URL);
  });

  it('refuses to guess in a production build', () => {
    // A deployed app pointed at localhost asks the user's own phone for the
    // API. Failing is the only honest outcome.
    expect(() => resolveApiBaseUrl(undefined, PROD)).toThrow(/EXPO_PUBLIC_API_BASE_URL/);
    expect(() => resolveApiBaseUrl('', PROD, '10.0.0.5:8081')).toThrow(/EXPO_PUBLIC_API_BASE_URL/);
  });
});
