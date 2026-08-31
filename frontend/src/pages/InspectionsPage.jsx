import { Link } from 'react-router-dom';

import { InspectionRow } from '../components/InspectionRow.jsx';
import { useComplianceHistory } from '../hooks/useComplianceHistory.js';

/**
 * Inspections: the compliance results already stored, newest first.
 *
 * `GET /api/v1/compliance/` - the history behind the scan screen and the
 * permalink. It lists what has been checked, when, and what came out; each row
 * links to `/result/<uuid>`, which remains the only place the findings, the
 * violations and the reading live. Nothing on this screen is a summary of a
 * result the API did not summarise.
 *
 * Four things here are deliberate:
 *
 * 1. **Pagination follows the API's own `next` / `previous` URLs.** No page
 *    number is built in the browser, and the page count is never guessed at:
 *    the total shown is the endpoint's `count`, and it is omitted entirely
 *    rather than estimated if the response did not carry one.
 * 2. **No filter, no sort control, no search box.** The endpoint offers none of
 *    them, and a control that appeared to narrow a list it cannot narrow would
 *    be a lie about what the user is looking at.
 * 3. **The list is not scoped to the viewer, and this screen does not pretend
 *    otherwise.** Every caller the backend lets through sees every stored
 *    check; that is a documented backend limitation, and hiding rows in
 *    JavaScript would conceal it without fixing it. Filtering in a browser is
 *    not authorisation.
 * 4. **Empty, failed and loading are three different screens.** "Nothing has
 *    been evaluated yet" is a real state of a working system and must never be
 *    drawn as an error, or as an empty table under a spinner that never stops.
 */
export function InspectionsPage() {
  const {
    data,
    error,
    isLoading,
    refresh,
    goToNextPage,
    goToPreviousPage,
    hasNextPage,
    hasPreviousPage,
  } = useComplianceHistory();

  const rows = data?.results ?? [];
  const isEmpty = Boolean(data) && rows.length === 0;

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <ol className="breadcrumb">
            <li>Inspections</li>
            <li>History</li>
          </ol>
          <h1 className="page-title">Inspections</h1>
          <p className="page-lede">
            Every compliance assessment stored by this installation, most recent
            first. Open one to see the rules that were examined, the violations
            recorded and the text the label was read to say.
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
          <span className="spinner" aria-hidden="true" /> Loading stored
          inspections…
        </p>
      )}

      {error && (
        <div className="panel panel--error" role="alert">
          <p>
            <strong>The inspection history could not be loaded.</strong>{' '}
            {error.message}
          </p>
          {error.status === 403 && (
            <p className="panel__hint">
              The analysis endpoints require an authenticated user unless the
              demonstration switch is on. Sign in, or set{' '}
              <code>DEMO_PUBLIC_ANALYSIS_API</code> in the backend environment.
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

      {isEmpty && (
        <div className="empty-state">
          <p>
            Nothing has been assessed yet. Scan a label and its result will be
            stored here — this list is the history of assessments this
            installation has made, not a catalogue of products.
          </p>
        </div>
      )}

      {rows.length > 0 && (
        <>
          <h2 className="section-heading">
            Stored assessments
            {/*
              The endpoint's own total, not the length of this page, and shown
              only when the response carried one.
            */}
            {typeof data.count === 'number' && ` (${data.count})`}
          </h2>

          <div className="history-list">
            {rows.map((row, index) => (
              <InspectionRow key={row.id ?? `row-${index}`} row={row} />
            ))}
          </div>
        </>
      )}

      {/*
        Rendered whenever a page has been loaded, including the last one - the
        controls are disabled at the ends rather than disappearing, so the
        position in the history does not have to be inferred from which buttons
        happen to exist.
      */}
      {data && rows.length > 0 && (
        <nav className="pagination" aria-label="Inspection history pages">
          <button
            type="button"
            className="button"
            onClick={goToPreviousPage}
            disabled={!hasPreviousPage || isLoading}
          >
            Previous page
          </button>
          <p className="pagination__status">
            Showing {rows.length} of{' '}
            {typeof data.count === 'number'
              ? `${data.count} stored assessment${data.count === 1 ? '' : 's'}`
              : 'the stored assessments'}
            .
          </p>
          <button
            type="button"
            className="button"
            onClick={goToNextPage}
            disabled={!hasNextPage || isLoading}
          >
            Next page
          </button>
        </nav>
      )}
    </section>
  );
}
