import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { ComplianceResult } from '../components/ComplianceResult.jsx';
import { ConfigurationPanel } from '../components/ConfigurationPanel.jsx';
import { ExtractionPanel } from '../components/ExtractionPanel.jsx';
import { PipelineStepper } from '../components/PipelineStepper.jsx';
import { UploadPanel } from '../components/UploadPanel.jsx';
import { PHASES, useLabelAnalysis } from '../hooks/useLabelAnalysis.js';
import { useApiHealth } from '../hooks/useApiHealth.js';

/**
 * Upload a label photograph and show what the system made of it.
 *
 * The Figma "Inspection Workspace" before analysis and "Compliance Assessment"
 * after it, over the real two-step backend flow:
 *
 *     POST /api/v1/extraction/  ->  run id  ->  POST /api/v1/compliance/
 *
 * Two steps rather than the one-shot `POST /api/v1/images/`, because the
 * reading and the verdict are different claims and this screen shows both. The
 * photograph is uploaded once; `useLabelAnalysis` holds the run id, so
 * retrying a failed verdict re-evaluates the reading the user is already
 * looking at rather than producing a new one that might read differently.
 *
 * Things on this page that are deliberate and should survive a redesign:
 *
 * 1. **The summary is shown next to the verdict, always.** It is what
 *    distinguishes "we checked and it passed" from "no rules are loaded, so
 *    nothing was checked".
 * 2. **REVIEW_REQUIRED is presented as a real outcome, not a soft pass.**
 * 3. **What was read is shown beside what was concluded**, under its own
 *    heading, so a reviewer can check a finding against the text it came from.
 * 4. **The two requests fail separately.** A failed compliance call leaves the
 *    reading on screen with a retry that does not re-upload.
 */
export function ScanPage() {
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [viewType, setViewType] = useState('unspecified');
  const [categoryCode, setCategoryCode] = useState('');
  const [copied, setCopied] = useState(false);

  const { data: health } = useApiHealth();
  const {
    phase,
    extraction,
    result,
    extractionError,
    complianceError,
    isEvaluating,
    isBusy,
    analyse,
    evaluate,
    reset,
  } = useLabelAnalysis();

  // The API stores what it measured from the photograph but serves no URL for
  // it, so the picture behind the evidence overlay is the local file. Revoked
  // on replacement and on unmount; an object URL that is never revoked keeps
  // the whole image alive in memory for the life of the tab.
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return undefined;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function handleSubmit(event) {
    event.preventDefault();
    if (!file || isBusy) {
      return;
    }
    setCopied(false);
    analyse(file, { viewType, categoryCode: categoryCode.trim() });
  }

  function handleReset() {
    setFile(null);
    setCopied(false);
    reset();
  }

  async function handleCopyLink() {
    const url = `${window.location.origin}/result/${result.id}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // Clipboard access is refused outside a secure context and in some
      // permission states. Rather than report a failure the user cannot act
      // on, fall back to putting the link on screen to be copied by hand.
      setCopied(false);
      window.prompt('Copy this link to the result:', url);
    }
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <ol className="breadcrumb">
            <li>Inspections</li>
            <li>{result ? `Result ${result.id.slice(0, 8)}` : 'New inspection'}</li>
          </ol>
          <h1 className="page-title">
            {result ? 'Compliance assessment' : 'Scan a package label'}
          </h1>
          <p className="page-lede">
            {result
              ? 'What the label was read to say, and what the loaded rules make of it.'
              : 'Upload a photograph of a packaged commodity label. The system reads the declarations it can find, then checks them against the rules loaded in this installation.'}
          </p>
        </div>

        {result && (
          <div className="page-header__actions">
            <button type="button" className="button" onClick={handleCopyLink}>
              {copied ? 'Link copied' : 'Copy result link'}
            </button>
            <button
              type="button"
              className="button button--primary"
              onClick={handleReset}
            >
              New scan
            </button>
          </div>
        )}
      </div>

      {phase !== PHASES.IDLE && <PipelineStepper phase={phase} />}

      {!result && (
        <form className="workspace" onSubmit={handleSubmit}>
          <div className="workspace__main">
            <UploadPanel
              file={file}
              health={health}
              disabled={isBusy}
              onFileSelected={(chosen) => {
                setFile(chosen);
                setCopied(false);
              }}
              onClear={handleReset}
            />
          </div>

          <div className="workspace__aside">
            <ConfigurationPanel
              categoryCode={categoryCode}
              onCategoryCodeChange={setCategoryCode}
              viewType={viewType}
              onViewTypeChange={setViewType}
              health={health}
              canSubmit={Boolean(file)}
              isBusy={isBusy}
              busyLabel={
                isEvaluating ? 'Checking rules…' : 'Reading label…'
              }
              onReset={handleReset}
            />
          </div>
        </form>
      )}

      {extractionError && (
        <div className="panel panel--error" role="alert">
          <p>
            <strong>The label could not be read.</strong>{' '}
            {extractionError.message}
          </p>
          <ErrorDetails details={extractionError.details} />
          {extractionError.status === 403 && (
            <p className="panel__hint">
              The analysis endpoints require an authenticated user unless the
              demonstration switch is on. Sign in, or set{' '}
              <code>DEMO_PUBLIC_ANALYSIS_API</code> in the backend environment.
            </p>
          )}
          {extractionError.isNetworkError && (
            <p className="panel__hint">
              Start the Django server with{' '}
              <code>python backend/manage.py runserver</code>.
            </p>
          )}
        </div>
      )}

      {complianceError && (
        <div className="panel panel--error" role="alert">
          <p>
            <strong>The label was read, but the rules could not be checked.</strong>{' '}
            {complianceError.message}
          </p>
          <ErrorDetails details={complianceError.details} />
          <p className="panel__hint">
            The reading is unaffected and is still held. Retrying evaluates the
            same reading — the photograph is not uploaded or read again.
          </p>
          <button
            type="button"
            className="button"
            disabled={isBusy}
            onClick={() => evaluate({ categoryCode: categoryCode.trim() })}
          >
            Check the rules again
          </button>
        </div>
      )}

      {result && <ComplianceResult result={result} imageUrl={previewUrl} />}

      {/*
        The reading, on its own, when there is no verdict to show it inside.
        Reached when the compliance call failed after extraction succeeded - the
        state the error above promises - and it must be a real promise: the user
        is told the reading is unaffected and still held, so it has to be
        visible. Under its own heading, with no verdict anywhere near it.
      */}
      {!result && extraction && (
        <>
          <h2 className="section-heading">Extraction — what was read</h2>
          <p className="page-lede">
            This is the reading. No rule has been applied to it, so nothing here
            is a compliance finding.
          </p>
          <ExtractionPanel extraction={extraction} />
        </>
      )}

      {result && (
        <p className="hint">
          This result is stored. It can be reopened at{' '}
          <Link to={`/result/${result.id}`}>/result/{result.id}</Link> — the
          photograph itself is not served back, so the evidence overlay is only
          available on this screen.
        </p>
      )}
    </section>
  );
}

/**
 * The API's per-field validation messages.
 *
 * Rendered as text, never as markup: this is server-generated content and the
 * details object is shaped by whatever field failed.
 */
function ErrorDetails({ details }) {
  if (!details || typeof details !== 'object') {
    return null;
  }

  return (
    <ul>
      {Object.entries(details).map(([field, messages]) => (
        <li key={field}>
          <strong>{field}:</strong>{' '}
          {Array.isArray(messages) ? messages.join(' ') : String(messages)}
        </li>
      ))}
    </ul>
  );
}
