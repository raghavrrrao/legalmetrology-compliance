import { Link } from 'react-router-dom';

import { InspectionRow } from '../components/InspectionRow.jsx';
import { StatusBadge } from '../components/StatusBadge.jsx';
import { useApiHealth } from '../hooks/useApiHealth.js';
import { useComplianceHistory } from '../hooks/useComplianceHistory.js';

/** How many stored inspections the home page shows before deferring to the list. */
const RECENT_LIMIT = 3;

/**
 * The landing page.
 *
 * It answers three questions, in the order somebody asks them:
 *
 *     What is this for?      the hero
 *     How does it work?      four steps
 *     What have I done?      recent inspections, or an empty state
 *
 * and then, last and closed, the diagnostics.
 *
 * **Why the diagnostics moved.** This page used to open with a "Backend
 * connection" card listing the API version, the database ping and the
 * Tesseract build. All three are real and all three are useful on a bad day,
 * and none of them is what somebody opens a compliance tool to find out. They
 * are now in a closed `<details>` at the bottom. Closed, not removed:
 * `<details>` keeps its contents in the DOM, so a page search still finds the
 * engine version and a screen reader still reads it on opening the disclosure.
 *
 * **What did NOT move.** The two honesty notices stay in the body, directly
 * under the hero. They are not diagnostics - they are the difference between
 * "this system checked your label" and "this system cannot currently check
 * anything, and what you are about to see is not a real reading". While the
 * engine is a placeholder or no verified rules are loaded, that has to be on
 * screen before anybody reaches the scan button, and burying it in a
 * disclosure with the database ping would be exactly the quiet demotion this
 * project refuses everywhere else.
 *
 * **Nothing on this page is invented.** The recent list is the compliance
 * history endpoint's own rows or an empty state; there is no inspection count,
 * no pass rate, no score and no sample product. The hero illustration draws
 * the *shape* of a label - the declaration names this extractor looks for -
 * with blank bars where values would be, because putting a fabricated MRP on
 * the front page of a tool that exists to check real ones would be absurd.
 */
export function HomePage() {
  const health = useApiHealth();

  return (
    <div className="home">
      <Hero />

      <HonestyNotices health={health} />

      <section aria-labelledby="how-it-works">
        <div className="home-section__head">
          <h2 className="section-heading" id="how-it-works">
            How an inspection works
          </h2>
        </div>
        <ol className="flow">
          {STEPS.map((step) => (
            <li className="flow__step glass" key={step.number}>
              <span className="flow__num" aria-hidden="true">
                {step.number}
              </span>
              <div className="flow__body">
                <h3 className="flow__title">{step.title}</h3>
                <p className="flow__text">{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <RecentInspections />

      <SystemStatus health={health} />
    </div>
  );
}

/* --- hero ------------------------------------------------------------------ */

function Hero() {
  return (
    <section className="hero">
      <div className="hero__copy">
        <p className="hero__eyebrow">
          <span aria-hidden="true">§</span>
          Legal Metrology (Packaged Commodities) Rules, 2011
        </p>

        <h1 className="hero__title">
          Check a package before you trust the label.
        </h1>

        <p className="hero__lede">
          Scan or upload a packaged-product label. We extract its declarations,
          compare them with the compliance requirements configured in this
          system, and show what needs attention.
        </p>

        <div className="hero__actions">
          <Link className="button button--primary button--large" to="/scan">
            Scan a label
          </Link>
          {/*
            The same destination, and honestly so: there is no camera capture
            on the web client, so "scan" and "upload" are two names for the one
            screen that accepts an image. Both are offered because people
            arrive looking for one word or the other.
          */}
          <Link className="button button--large" to="/scan">
            Upload images
          </Link>
        </div>

        <p className="hero__note">
          <span aria-hidden="true">🛈</span>
          Automated assistance for a human reviewer — never a legal
          determination.
        </p>
      </div>

      <div className="hero__visual">
        <LabelIllustration />
      </div>
    </section>
  );
}

/**
 * The hero illustration: what a label inspection looks like, not a product.
 *
 * `aria-hidden` throughout. It carries nothing the copy beside it does not
 * already say, and describing a decorative drawing to a screen reader would
 * add noise rather than information.
 *
 * The declaration names are the real vocabulary this extractor looks for. The
 * values are blank bars. That distinction is the point: the picture shows the
 * *shape* of a reading without asserting a single fact about any package.
 */
function LabelIllustration() {
  return (
    <div className="label-card glass" aria-hidden="true">
      <div className="label-card__panel">
        <span className="label-card__frame" />

        <div className="label-card__brand">
          <span className="label-card__swatch" />
          <span className="label-card__bars">
            <span className="label-card__bar label-card__bar--medium" />
            <span className="label-card__bar label-card__bar--short" />
          </span>
        </div>

        {ILLUSTRATED_FIELDS.map((field) => (
          <div className="label-card__row" key={field.name}>
            <span className="label-card__field">{field.name}</span>
            <span
              className={`label-card__bar label-card__bar--${field.width}`}
              style={{ flex: 1 }}
            />
            {field.read && <span className="label-card__tick">✓</span>}
          </div>
        ))}
      </div>

      <div className="label-card__chips">
        <span className="label-card__chip label-card__chip--read">
          ✓ 4 declarations read
        </span>
        <span className="label-card__chip">1 needs review</span>
      </div>
    </div>
  );
}

/**
 * Declaration names only — the vocabulary in `LabelFieldKey`. No values.
 *
 * `read` decides whether a tick is drawn, so the illustration shows both
 * outcomes a real reading produces. The counts on the chips below match this
 * list; they describe the drawing and nothing else.
 */
const ILLUSTRATED_FIELDS = Object.freeze([
  { name: 'Net quantity', width: 'medium', read: true },
  { name: 'Retail price', width: 'short', read: true },
  { name: 'Mfg. date', width: 'short', read: true },
  { name: 'Consumer care', width: 'medium', read: true },
  { name: 'Country of origin', width: 'short', read: false },
]);

/* --- how it works ---------------------------------------------------------- */

const STEPS = Object.freeze([
  {
    number: '01',
    title: 'Scan',
    text: 'Capture or upload one or more images of the package label.',
  },
  {
    number: '02',
    title: 'Extract',
    text: 'Text recognition locates the declarations printed on the package.',
  },
  {
    number: '03',
    title: 'Check',
    text: 'Deterministic rules evaluate the requirements that apply to it.',
  },
  {
    number: '04',
    title: 'Review',
    text: 'See every finding with its evidence, and what still needs a person.',
  },
]);

/* --- honesty notices -------------------------------------------------------- */

/**
 * The two notices that must not be quietly demoted, and the connection error.
 *
 * While the engine is a placeholder or no verified rules are loaded, the
 * system cannot produce a real finding. Saying so here, above the fold, is
 * what stops a demonstration implying otherwise.
 */
function HonestyNotices({ health }) {
  const { data, error, refresh } = health;

  return (
    <>
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
          <button type="button" className="button" onClick={refresh}>
            Try again
          </button>
          {/*
            Measured in Chrome: after the backend has actually been down, an
            in-page retry keeps failing at the connection layer - the request
            never reaches Django - while reloading the document succeeds
            immediately. The retry itself is correct (see
            hooks/useApiHealth.test.jsx), so rather than work around a browser
            behaviour we tell the user the thing that always works.
          */}
          <p className="panel__hint">
            If retrying does not help once the backend is running, reload the
            page — the browser can hold on to the failed connection.
          </p>
        </div>
      )}

      {data?.extractionEngine.isPlaceholder && (
        <p className="panel panel--warning">
          <strong>No OCR engine is installed.</strong> The extraction pipeline
          is wiring only: it reads no text from images and produces no label
          data. Results shown anywhere in this system are not real readings.
        </p>
      )}

      {data?.complianceRules?.verified === 0 && (
        <p className="panel panel--warning">
          <strong>No verified compliance rules are loaded.</strong>{' '}
          {data.complianceRules.unverified > 0
            ? `${data.complianceRules.unverified} unverified rule(s) are present; these can flag a product for review but can never mark it non-compliant.`
            : 'Nothing can be checked, so every product will be reported as needing review.'}
        </p>
      )}
    </>
  );
}

/* --- recent inspections ----------------------------------------------------- */

/**
 * The most recent stored inspections, or a polished empty state.
 *
 * Real rows from `GET /api/v1/compliance/` — the same endpoint and the same
 * `InspectionRow` the Inspections screen uses, so a row cannot say one thing
 * here and another there. No count, no rate, no summary statistic: the list
 * endpoint returns rows, and rows are what is shown.
 *
 * A failure here is deliberately quiet. History is a convenience on this page,
 * not its purpose, and an alert about it would compete with the connection
 * error the notices above already raise for the same outage.
 */
function RecentInspections() {
  const { data, error, isLoading } = useComplianceHistory();
  const rows = (data?.results ?? []).slice(0, RECENT_LIMIT);
  const hasMore = (data?.count ?? 0) > rows.length;

  return (
    <section className="recent glass" aria-labelledby="recent-inspections">
      <div className="home-section__head">
        <h2 className="section-heading" id="recent-inspections">
          Recent inspections
        </h2>
        {rows.length > 0 && hasMore && (
          <Link className="button button--link" to="/inspections">
            View all
          </Link>
        )}
      </div>

      {isLoading && (
        <p className="hint" role="status">
          <span className="spinner" aria-hidden="true" /> Loading recent
          inspections…
        </p>
      )}

      {!isLoading && error && (
        <p className="hint">
          Recent inspections could not be loaded. They are still available on
          the <Link to="/inspections">Inspections</Link> screen.
        </p>
      )}

      {!isLoading && !error && rows.length === 0 && (
        <div className="recent__empty">
          <span className="recent__empty-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="24" height="24" fill="none">
              <rect
                x="3"
                y="5"
                width="18"
                height="14"
                rx="2.5"
                stroke="currentColor"
                strokeWidth="1.6"
              />
              <path
                d="M3 16.2l4.6-4.1 3.8 3.3 3.1-2.6L21 16.6"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          <h3 className="recent__empty-title">No inspections yet</h3>
          <p className="recent__empty-text">
            Your scanned products will appear here.
          </p>
          <Link className="button button--primary" to="/scan">
            Start your first inspection
          </Link>
        </div>
      )}

      {!isLoading && !error && rows.length > 0 && (
        <div className="history-list">
          {rows.map((row) => (
            <InspectionRow key={row.id ?? row.createdAt} row={row} />
          ))}
        </div>
      )}
    </section>
  );
}

/* --- system status ---------------------------------------------------------- */

/**
 * The diagnostics, closed by default and last on the page.
 *
 * The dot on the summary is a second signal, never the only one: the badge
 * inside says the word, and the summary text says "System status" whatever the
 * dot is doing.
 */
function SystemStatus({ health }) {
  const { data, error, isLoading } = health;
  const tone = error ? 'bad' : data?.status === 'ok' ? 'ok' : '';

  return (
    <details className="system-status">
      <summary>
        <span
          className={`system-status__dot${tone ? ` system-status__dot--${tone}` : ''}`}
          aria-hidden="true"
        />
        System status
      </summary>

      <div className="system-status__body">
        {isLoading && (
          <p className="hint" role="status">
            <span className="spinner" aria-hidden="true" /> Checking backend…
          </p>
        )}

        {error && (
          <p className="hint">
            The backend could not be reached. {error.message}
          </p>
        )}

        {data && (
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
              {data.extractionEngine.isPlaceholder && ' — placeholder'}
            </dd>

            {data.complianceRules && (
              <>
                <dt>Compliance rules</dt>
                <dd>
                  {data.complianceRules.verified} verified,{' '}
                  {data.complianceRules.unverified} unverified
                </dd>
              </>
            )}
          </dl>
        )}
      </div>
    </details>
  );
}
