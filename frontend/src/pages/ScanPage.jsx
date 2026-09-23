import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { AnalysisPanel } from '../components/AnalysisPanel.jsx';
import { ApplicabilityForm } from '../components/ApplicabilityForm.jsx';
import { ComplianceResult } from '../components/ComplianceResult.jsx';
import { ConfigurationPanel } from '../components/ConfigurationPanel.jsx';
import { ExtractionPanel } from '../components/ExtractionPanel.jsx';
import { UploadPanel } from '../components/UploadPanel.jsx';
import { WorkflowProgress } from '../components/WorkflowProgress.jsx';
import { useLabelAnalysis } from '../hooks/useLabelAnalysis.js';
import { config } from '../config/env.js';
import { useApiHealth } from '../hooks/useApiHealth.js';
import { useApplicabilityConditions } from '../hooks/useApplicabilityConditions.js';

/**
 * Upload a label photograph and show what the system made of it.
 *
 * Four numbered steps before the check, over the real two-step backend flow:
 *
 *     POST /api/v1/extraction/  ->  run id  ->  POST /api/v1/compliance/
 *
 * Two requests rather than the one-shot `POST /api/v1/images/`, because the
 * reading and the verdict are different claims and this screen shows both. The
 * photograph is uploaded once; `useLabelAnalysis` holds the run id, so
 * retrying a failed verdict re-evaluates the reading the user is already
 * looking at rather than producing a new one that might read differently.
 *
 * **The steps are a reading order, not a wizard.** Every control stays on the
 * page and reachable at once; what the numbers do is tell somebody who has
 * never seen the screen what to do first, and let them stop after step one if
 * that is all they have. A wizard that hid step 2 until step 1 was "complete"
 * would make the optional steps feel mandatory and would put a gate in front of
 * a user who only wants to press the button.
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
 * 5. **The declarations are optional and unanswered is never "no".** The facts
 *    several clauses turn on cannot be seen in a photograph, so the user may
 *    state them - and leaving one unstated is a supported choice that costs a
 *    REVIEW REQUIRED on that clause rather than a guess. After a result, the
 *    same facts can be stated and the *same reading* re-evaluated, which is the
 *    intended way to resolve a review without re-uploading anything.
 */
export function ScanPage() {
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [viewType, setViewType] = useState('unspecified');
  const [categoryCode, setCategoryCode] = useState('');
  const [copied, setCopied] = useState(false);
  // One entry per question the user has actually answered. A question with no
  // entry is UNANSWERED, which is not "no" - `evaluateExtractionRun` drops the
  // empty ones and the engine treats a missing answer as unestablished.
  const [declarations, setDeclarations] = useState({});

  const { data: health } = useApiHealth();
  const {
    data: conditions,
    error: conditionsError,
    isLoading: conditionsLoading,
  } = useApplicabilityConditions();
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

  const setDeclaration = useCallback((code, answer) => {
    setDeclarations((current) => {
      const next = { ...current };
      if (answer === '') {
        // Removed rather than stored as an empty string, so "the user cleared
        // this" and "the user never touched it" are the same state - which is
        // what they mean to the engine.
        delete next[code];
      } else {
        next[code] = answer;
      }
      return next;
    });
  }, []);

  const clearDeclarations = useCallback(() => setDeclarations({}), []);

  function handleSubmit(event) {
    event.preventDefault();
    if (!file || isBusy) {
      return;
    }
    setCopied(false);
    analyse(file, {
      viewType,
      categoryCode: categoryCode.trim(),
      declarations,
    });
  }

  function handleReset() {
    setFile(null);
    setCopied(false);
    setDeclarations({});
    reset();
  }

  /**
   * Re-run the rules over the reading already held, with the facts now stated.
   *
   * The photograph is not uploaded or read again - `useLabelAnalysis` keeps the
   * run id - so the reading on screen and the new verdict are provably about
   * the same evidence. This is what turns a REVIEW REQUIRED the user can
   * resolve into one they actually can.
   */
  function handleReEvaluate() {
    setCopied(false);
    evaluate({ categoryCode: categoryCode.trim(), declarations });
  }

  /**
   * A person confirming (or correcting) the product type the classifier
   * proposed. The chosen code becomes the stated category and the same
   * reading is re-checked - exactly the manual path, one click shorter. The
   * classifier's suggestion is never sent on its own; only what was chosen.
   */
  function handleConfirmCategory(code) {
    setCopied(false);
    setCategoryCode(code);
    evaluate({ categoryCode: code, declarations });
  }

  /**
   * A person answering a fact the label suggested - yes, no, or not sure.
   * Recorded as their declaration, never as the classifier's, and the same
   * reading is re-checked with it.
   */
  function handleConfirmFact(code, answer) {
    setCopied(false);
    const next = { ...declarations, [code]: answer };
    setDeclarations(next);
    evaluate({ categoryCode: categoryCode.trim(), declarations: next });
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

  const answeredCount = Object.values(declarations).filter(Boolean).length;

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <ol className="breadcrumb">
            <li>
              <Link to="/inspections">Inspections</Link>
            </li>
            <li>{result ? `Result ${result.id.slice(0, 8)}` : 'New inspection'}</li>
          </ol>
          <h1 className="page-title">
            {result ? 'Compliance assessment' : 'Check a packaged product label'}
          </h1>
          <p className="page-lede">
            {result
              ? 'What the label was read to say, and what the loaded rules make of it.'
              : 'Upload a clear photo of the product label. We read the information we can find on it and check the requirements that apply.'}
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

      <WorkflowProgress
        phase={phase}
        hasFile={Boolean(file)}
        hasDetails={Boolean(categoryCode.trim()) || answeredCount > 0}
        hasResult={Boolean(result)}
      />

      {/*
        While a request is in flight the form is replaced rather than merely
        disabled. A greyed-out form with a spinner on its submit button tells a
        user what they cannot do; this tells them what the system is doing, and
        does it with their own photograph in front of them.

        It is not a step the flow has to pass through - the moment either
        request settles this unmounts and the form or the result takes its
        place, so nothing is gated behind an animation.
      */}
      {!result && isBusy && (
        <AnalysisPanel
          previewUrl={previewUrl}
          fileName={file?.name}
          phase={phase}
          // Counted from the extraction response once it exists, and undefined
          // until then. Never estimated: an unknown count shows no count.
          declarationsRead={extraction?.fieldsRead?.length}
        />
      )}

      {!result && !isBusy && (
        <form className="scan-flow" onSubmit={handleSubmit}>
          <UploadPanel
            file={file}
            previewUrl={previewUrl}
            health={health}
            disabled={isBusy}
            onFileSelected={(chosen) => {
              setFile(chosen);
              setCopied(false);
            }}
            onClear={handleReset}
          />

          <ConfigurationPanel
            categoryCode={categoryCode}
            onCategoryCodeChange={setCategoryCode}
            viewType={viewType}
            onViewTypeChange={setViewType}
            health={health}
            isBusy={isBusy}
          />

          <ApplicabilityForm
            catalogue={conditions}
            isLoading={conditionsLoading}
            error={conditionsError}
            answers={declarations}
            onChange={setDeclaration}
            onClearAll={clearDeclarations}
            disabled={isBusy}
          />

          <section className="ready glass">
            <h2 className="ready__title">Ready to check</h2>
            <p className="ready__text">
              Review the information above, then run the compliance check. We
              read the label and compare what we can identify against the
              requirements that apply.
            </p>

            <dl className="review-summary">
              <dt>Photo</dt>
              <dd>{file ? file.name : 'No photo chosen yet'}</dd>
              <dt>Product type</dt>
              <dd>{categoryCode.trim() || 'Not specified'}</dd>
              <dt>Part of package</dt>
              <dd>{viewTypeLabel(viewType)}</dd>
              <dt>Questions answered</dt>
              <dd>
                {answeredCount === 0
                  ? 'None — anything that depends on them will be reported as requiring review'
                  : `${answeredCount} of ${conditions?.conditions.length ?? 0}`}
              </dd>
            </dl>

            <div className="ready__actions">
              <button
                type="submit"
                className="button button--primary button--large button--block"
                disabled={!file || isBusy}
              >
                {isBusy ? (
                  <>
                    <span className="spinner" aria-hidden="true" />
                    {isEvaluating ? 'Checking requirements…' : 'Reading label…'}
                  </>
                ) : (
                  'Check compliance'
                )}
              </button>
              <button
                type="button"
                className="button button--block"
                onClick={handleReset}
                disabled={isBusy}
              >
                Clear
              </button>
            </div>

            {!file && (
              <p className="hint hint--centred">
                Upload a photo above to start the check.
              </p>
            )}

            <p className="ready__note">
              Automated assistance · Human review may be required
            </p>
          </section>
        </form>
      )}

      {extractionError && (
        <div className="panel panel--error" role="alert">
          <p>
            <strong>We could not read this photo.</strong>{' '}
            {friendlyExtractionError(extractionError)}
          </p>
          {extractionError.status === 403 && (
            <p className="panel__hint">
              Analysis requires a signed-in user on this deployment, unless the
              public demonstration mode (
              <code>DEMO_PUBLIC_ANALYSIS_API</code>) is switched on.
            </p>
          )}
          {/*
            Developer guidance, and only where a developer is: telling a
            demonstration audience to run `manage.py runserver` names a machine
            they do not have and an action they cannot take. `isDevelopment` is
            the flag this project keeps for exactly this - an affordance, never
            an authorisation.
          */}
          {extractionError.isNetworkError && config.isDevelopment && (
            <p className="panel__hint">
              Start the Django server with{' '}
              <code>python backend/manage.py runserver</code>.
            </p>
          )}
          <ErrorDetails error={extractionError} />
        </div>
      )}

      {complianceError && (
        <div className="panel panel--error" role="alert">
          <p>
            <strong>We read the label, but could not finish the check.</strong>{' '}
            {complianceError.message}
          </p>
          <p className="panel__hint">
            Nothing has been lost. Trying again checks the same reading — the
            photo is not uploaded or read a second time.
          </p>
          <button
            type="button"
            className="button"
            disabled={isBusy}
            onClick={() =>
              evaluate({ categoryCode: categoryCode.trim(), declarations })
            }
          >
            Check the rules again
          </button>
          <ErrorDetails error={complianceError} />
        </div>
      )}

      {result && (
        <>
          <ComplianceResult
            result={result}
            imageUrl={previewUrl}
            disabled={isBusy}
            onConfirmCategory={handleConfirmCategory}
            onConfirmFact={handleConfirmFact}
          />

          {/*
            Offered after the verdict, not only before it. A user learns which
            facts mattered by reading the findings that could not be decided
            without them, and at that point re-checking must not cost another
            upload - it evaluates the same stored reading.
          */}
          <h2 className="section-heading">Help us finish this check</h2>
          <p className="section-lede">
            Some requirements depend on information that a photograph cannot
            establish. Answer what you know and check the same reading again —
            the photo is not uploaded or read a second time.
          </p>
          <ApplicabilityForm
            catalogue={conditions}
            isLoading={conditionsLoading}
            error={conditionsError}
            answers={declarations}
            onChange={setDeclaration}
            onClearAll={clearDeclarations}
            disabled={isBusy}
          />
          <p className="field field--actions">
            <button
              type="button"
              className="button button--primary"
              disabled={isBusy}
              onClick={handleReEvaluate}
            >
              {isEvaluating ? (
                <>
                  <span className="spinner" aria-hidden="true" />
                  Checking requirements…
                </>
              ) : (
                'Check the rules again'
              )}
            </button>
          </p>
        </>
      )}

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

/** The label for a view type, for the review summary. */
function viewTypeLabel(value) {
  const labels = {
    unspecified: 'Not specified',
    front: 'Front panel',
    back: 'Back panel',
    principal_display: 'Principal display panel',
    label: 'Label close-up',
    other: 'Other',
  };
  return labels[value] ?? value;
}

/**
 * A sentence a submitter can act on, for the failures that have one.
 *
 * Only the cases where the cause is genuinely known are reworded. Everything
 * else falls through to the backend's own message, which is written for a
 * person and is more specific than any generic sentence this file could offer —
 * an oversized upload says what the limit was, and replacing that with "unable
 * to upload this image" would lose the one fact the user needed.
 */
function friendlyExtractionError(error) {
  if (error.isNetworkError) {
    return 'We could not reach the server. Check your connection and try again.';
  }
  if (error.code === 'timeout') {
    return 'The request took too long. Try again, or try a smaller photo.';
  }
  if (error.status === 403) {
    return 'This server did not allow the request.';
  }
  return error.message;
}

/**
 * The API's per-field validation messages, behind a disclosure.
 *
 * Rendered as text, never as markup: this is server-generated content and the
 * details object is shaped by whatever field failed. The error code travels
 * with it because it is what somebody debugging will ask for first, and it is
 * meaningless to everybody else — which is exactly what a disclosure is for.
 */
function ErrorDetails({ error }) {
  const details = error?.details;
  const hasFields = details && typeof details === 'object';

  return (
    <details className="technical-details">
      <summary>Technical details</summary>
      <dl className="detail-list">
        <dt>Error code</dt>
        <dd>
          <code>{error.code}</code>
        </dd>
        <dt>HTTP status</dt>
        <dd>{error.status === 0 ? 'No response received' : error.status}</dd>
      </dl>
      {hasFields && (
        <ul>
          {Object.entries(details).map(([field, messages]) => (
            <li key={field}>
              <strong>{field}:</strong>{' '}
              {Array.isArray(messages) ? messages.join(' ') : String(messages)}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
