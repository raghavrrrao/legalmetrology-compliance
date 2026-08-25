import { StatusBadge } from '../components/StatusBadge.jsx';
import { useApiHealth } from '../hooks/useApiHealth.js';

/**
 * The landing page.
 *
 * Its job in the base structure is to prove the frontend can reach the Django
 * API and to state plainly what the system can and cannot currently do. When
 * `feature/frontend-dashboard` builds the real UI, the health panel can move
 * to a diagnostics screen - but the honesty notice should survive.
 */
export function HomePage() {
  const { data, error, isLoading, refresh } = useApiHealth();

  return (
    <section className="page">
      <h1>Packaged commodity compliance</h1>
      <p>
        Upload a photograph of a packaged product label to have its declarations
        extracted and checked against the compliance rules loaded in this
        system.
      </p>

      <h2>Backend connection</h2>

      {isLoading && <p>Checking backend…</p>}

      {error && (
        <div className="panel panel--error" role="alert">
          <p>
            <strong>Could not reach the backend.</strong> {error.message}
          </p>
          {error.isNetworkError && (
            <p>
              Start the Django server with{' '}
              <code>python backend/manage.py runserver</code> and confirm{' '}
              <code>VITE_API_BASE_URL</code> in <code>frontend/.env</code>.
            </p>
          )}
          <button type="button" onClick={refresh}>
            Try again
          </button>
          {/*
            Measured in Chrome: after the backend has actually been down, an
            in-page retry keeps failing at the connection layer - the request
            never reaches Django - while reloading the document succeeds
            immediately. The retry itself is correct (see
            hooks/useApiHealth.test.jsx), so rather than work around a browser
            behaviour we tell the user the thing that always works. Saying
            "Try again" alone would send them in circles.
          */}
          <p className="panel__hint">
            If retrying does not help once the backend is running, reload the
            page - the browser can hold on to the failed connection.
          </p>
        </div>
      )}

      {data && (
        <div className="panel">
          <dl className="status-list">
            <dt>API</dt>
            <dd>
              <StatusBadge
                value={data.status}
                tone={data.status === 'ok' ? 'success' : 'warning'}
              />{' '}
              (version {data.apiVersion})
            </dd>

            <dt>Database</dt>
            <dd>
              <StatusBadge
                value={data.dependencies.database}
                tone={data.dependencies.database === 'ok' ? 'success' : 'error'}
              />
            </dd>

            <dt>Extraction engine</dt>
            <dd>
              {data.extractionEngine.name} {data.extractionEngine.version}
            </dd>
          </dl>

          {/*
            Two notices that must not be quietly removed once the UI gets
            prettier. While the engine is a placeholder or no verified rules
            are loaded, the system cannot produce a real finding, and saying so
            here is what stops a demo from implying otherwise.
          */}
          {data.extractionEngine.isPlaceholder && (
            <p className="panel panel--warning">
              <strong>No OCR engine is installed.</strong> The extraction
              pipeline is wiring only: it reads no text from images and produces
              no label data. Results shown anywhere in this system are not real
              readings.
            </p>
          )}

          {data.complianceRules?.verified === 0 && (
            <p className="panel panel--warning">
              <strong>No verified compliance rules are loaded.</strong>{' '}
              {data.complianceRules.unverified > 0
                ? `${data.complianceRules.unverified} unverified rule(s) are present; these can flag a product for review but can never mark it non-compliant.`
                : 'Nothing can be checked, so every product will be reported as needing review.'}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
