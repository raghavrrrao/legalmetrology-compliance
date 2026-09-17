/**
 * Is the analysis server reachable from this app, at the address this build
 * was given?
 *
 * Asked once when the home screen mounts and again on request. It exists
 * because the two most likely reasons an upload fails on a phone - no signal,
 * and a development build pointed at a laptop that is not running the backend
 * - look identical from inside the app, and only a request through the same
 * client at the same base URL can tell them apart. The web client asks the
 * same question on its home page (`useApiHealth` there).
 *
 * In a development build the resolved target is logged once, so the Metro
 * console says where requests go before any is made. The value is public
 * configuration; there is nothing secret to redact.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchHealth, type HealthStatus } from '../api/health';
import { config, describeApiTarget } from '../config/env';
import { logError } from '../utils/errors';

export type HealthCheckState =
  | { phase: 'checking'; target: ReturnType<typeof describeApiTarget> }
  | { phase: 'ok'; target: ReturnType<typeof describeApiTarget>; health: HealthStatus }
  | { phase: 'unreachable'; target: ReturnType<typeof describeApiTarget>; error: unknown };

let loggedTarget = false;

export function useApiHealth(): HealthCheckState & { check: () => void } {
  const target = describeApiTarget(config.apiBaseUrl);
  const [state, setState] = useState<HealthCheckState>({ phase: 'checking', target });
  const abortRef = useRef<AbortController | null>(null);

  // Starts the request; state changes only when it settles. Kept apart from
  // `check` so the mount effect sets no state synchronously.
  const run = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    if (config.isDevelopment && !loggedTarget) {
      loggedTarget = true;
      console.info(
        `[api] target ${target.origin}${target.path} (https: ${target.https}; ${config.apiBaseUrlSource})`,
      );
    }

    fetchHealth({ signal: controller.signal }).then(
      (health) => {
        if (!controller.signal.aborted) {
          setState({ phase: 'ok', target, health });
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          logError('health', error);
          setState({ phase: 'unreachable', target, error });
        }
      },
    );
    // `target` is derived from frozen config and never changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Ask again, showing the checking state while the request is in flight. */
  const check = useCallback(() => {
    setState({ phase: 'checking', target });
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run]);

  useEffect(() => {
    run();
    return () => abortRef.current?.abort();
  }, [run]);

  return { ...state, check };
}
