/**
 * Loads the declarable facts, in the {data, error, isLoading, refresh} shape
 * `useApiHealth` set.
 *
 * The catalogue is a property of the installation rather than of a submission -
 * it changes only when rules or the legal framework are reloaded - so it is
 * fetched once when the screen mounts and not per analysis.
 *
 * A failure here is deliberately **not** fatal to the scan flow. The
 * declarations are optional: without them the engine reports REVIEW REQUIRED on
 * the clauses that turn on an undeclared fact, which is a correct result rather
 * than a broken one. So the caller renders a notice and still lets the user
 * analyse a label.
 */

import { useCallback, useEffect, useState } from 'react';

import { fetchApplicabilityConditions } from '../services/applicabilityService.js';

export function useApplicabilityConditions() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);

  const refresh = useCallback(() => setReloadToken((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    setIsLoading(true);
    setError(null);

    fetchApplicabilityConditions({ signal: controller.signal })
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
