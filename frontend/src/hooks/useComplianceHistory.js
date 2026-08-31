/**
 * Loads a page of inspection history and walks between pages.
 *
 * The {data, error, isLoading, refresh} shape `useApiHealth` set, with the two
 * page moves added - because that is the whole of the extra state this screen
 * has. There is no global store for history and there should not be: a page of
 * results is asked for again by URL whenever it is needed, and nothing outside
 * the Inspections screen reads it.
 *
 * The page is identified by the backend's own `next` / `previous` URL, held in
 * state and passed straight back to the service. No page number is computed
 * here. That matters beyond tidiness: the page size is the server's to choose,
 * and a client that builds `?page=n` silently walks a different sequence the
 * moment it changes.
 *
 * `error` is a value, not a thrown exception - a history screen against a
 * stopped backend renders the failure and a retry rather than crashing.
 */

import { useCallback, useEffect, useState } from 'react';

import { fetchComplianceHistory } from '../services/complianceService.js';

export function useComplianceHistory() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  // null means "the first page", which is what the endpoint returns with no
  // query. Anything else is a URL the backend itself built.
  const [pageUrl, setPageUrl] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);

  const refresh = useCallback(() => setReloadToken((n) => n + 1), []);

  useEffect(() => {
    // Guards against setting state after unmount, which React warns about and
    // which happens routinely under StrictMode's double-invoked effects.
    const controller = new AbortController();
    let active = true;

    setIsLoading(true);
    setError(null);

    fetchComplianceHistory({ url: pageUrl, signal: controller.signal })
      .then((page) => {
        if (active) {
          setData(page);
        }
      })
      .catch((cause) => {
        if (active) {
          setError(cause);
          // Cleared rather than left stale: the rows on screen would otherwise
          // be from a page the user has already navigated away from, sitting
          // under an error about the page they asked for. `refresh` re-requests
          // that same page, which is the recovery.
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
  }, [pageUrl, reloadToken]);

  // Both no-ops at the ends of the history. The UI disables the controls there
  // too, but a keyboard or a double click must not be able to request a page
  // the API did not offer.
  const goToNextPage = useCallback(() => {
    setPageUrl((current) => data?.next ?? current);
  }, [data]);

  const goToPreviousPage = useCallback(() => {
    setPageUrl((current) => data?.previous ?? current);
  }, [data]);

  return {
    data,
    error,
    isLoading,
    refresh,
    goToNextPage,
    goToPreviousPage,
    hasNextPage: Boolean(data?.next),
    hasPreviousPage: Boolean(data?.previous),
  };
}
