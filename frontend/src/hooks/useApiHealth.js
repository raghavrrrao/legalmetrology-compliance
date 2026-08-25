/**
 * Loads backend health and exposes it as {data, error, isLoading, refresh}.
 *
 * This is the shape every data-loading hook in the app should follow, so a
 * teammate adding `useAnalysis` has a pattern to copy rather than inventing
 * one. Note that `error` is a value, not a thrown exception: a failed health
 * check is expected during setup and the UI renders it, rather than crashing.
 */

import { useCallback, useEffect, useState } from 'react';

import { fetchHealth } from '../services/healthService.js';

export function useApiHealth() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);

  const refresh = useCallback(() => setReloadToken((n) => n + 1), []);

  useEffect(() => {
    // Guards against setting state after unmount, which React warns about and
    // which happens routinely under StrictMode's double-invoked effects.
    const controller = new AbortController();
    let active = true;

    setIsLoading(true);
    setError(null);

    fetchHealth({ signal: controller.signal })
      .then((result) => {
        if (active) {
          setData(result);
        }
      })
      .catch((cause) => {
        if (active) {
          setError(cause);
          setData(null);
        }
      })
      .finally(() => {
        if (active) {
          setIsLoading(false);
        }
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [reloadToken]);

  return { data, error, isLoading, refresh };
}
