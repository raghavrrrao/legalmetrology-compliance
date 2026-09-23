import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { ComplianceResult } from '../components/ComplianceResult.jsx';
import { fetchComplianceResult } from '../services/complianceService.js';

/**
 * A stored compliance result, reopened by id.
 *
 * `GET /api/v1/compliance/<uuid>/` exists so a result survives a page reload
 * and can be sent to a reviewer as a link, and this is the screen that link
 * opens. The id is a UUID precisely so holding one result's link does not let
 * anyone walk to another's.
 *
 * The same `ComplianceResult` component as the scan flow, with one honest
 * difference: no `imageUrl`. The photograph lives in the browser it was
 * uploaded from and the API serves no bytes back, so the evidence panel says
 * the picture is unavailable rather than showing an empty frame. Everything
 * else - verdict, summary, findings, violations, the reading - is served by the
 * API and is identical to what the uploader saw.
 */
export function ResultPage() {
  const { checkId } = useParams();
  const [result, setResult] = useState(null);
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

    fetchComplianceResult(checkId, { signal: controller.signal })
      .then((data) => {
        if (active) {
          setResult(data);
        }
      })
      .catch((cause) => {
        if (active) {
          setError(cause);
          setResult(null);
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
  }, [checkId, reloadToken]);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <ol className="breadcrumb">
            <li>
              <Link to="/inspections">Inspections</Link>
            </li>
            <li>Result {String(checkId).slice(0, 8)}</li>
          </ol>
          <h1 className="page-title">Inspection report</h1>
          {/*
            "A stored result, loaded from the API by its id" described the
            plumbing rather than the page. What a reader needs to know here is
            that this is a saved record they can come back to and send on - the
            reason the route exists at all.
          */}
          <p className="page-lede">
            A saved record of one label check. This link reopens it, and can be
            sent to a reviewer.
          </p>
        </div>
        <div className="page-header__actions">
          <Link className="button button--primary" to="/scan">
            New scan
          </Link>
        </div>
      </div>

      {isLoading && (
        <p className="panel" role="status">
          <span className="spinner" aria-hidden="true" /> Loading the stored
          result…
        </p>
      )}

      {error && (
        <div className="panel panel--error" role="alert">
          <p>
            <strong>That result could not be loaded.</strong> {error.message}
          </p>
          {error.status === 404 && (
            <p className="panel__hint">
              No result exists with this id. Check the link, or run a new scan.
            </p>
          )}
          {error.isNetworkError && (
            <p className="panel__hint">
              Start the Django server with{' '}
              <code>python backend/manage.py runserver</code>.
            </p>
          )}
          <button type="button" className="button" onClick={refresh}>
            Try again
          </button>
        </div>
      )}

      {result && <ComplianceResult result={result} imageUrl={null} />}
    </section>
  );
}
