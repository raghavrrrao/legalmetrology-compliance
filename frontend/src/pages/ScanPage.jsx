import { useRef, useState } from 'react';

import { StatusBadge } from '../components/StatusBadge.jsx';
import { analyseImage } from '../services/complianceService.js';
import { formatFileSize, humaniseCode } from '../utils/format.js';

/**
 * Upload a label photograph and show what the system made of it.
 *
 * The whole demonstration flow on one screen: pick a file, watch it process,
 * read the verdict with the findings and the evidence behind them.
 *
 * Three things on this page are deliberate and should survive a redesign:
 *
 * 1. **The summary is shown next to the verdict, always.** The engine's
 *    explanation is what distinguishes "we checked and it passed" from "no
 *    rules are loaded, so nothing was checked". A verdict shown alone would
 *    imply a determination the system did not make.
 * 2. **REVIEW_REQUIRED is presented as a real outcome, not a soft pass.** It
 *    means a human needs to look at this.
 * 3. **What was read is shown beside what was concluded.** A reviewer must be
 *    able to check a finding against the text it came from.
 */

/** Which tone the shared badge component should use for each verdict. */
const TONE_BY_RESULT = {
  compliant: 'success',
  partially_compliant: 'warning',
  non_compliant: 'error',
  review_required: 'warning',
};

const VIEW_TYPES = [
  ['unspecified', 'Not specified'],
  ['front', 'Front panel'],
  ['back', 'Back panel'],
  ['principal_display', 'Principal display panel'],
  ['label', 'Label close-up'],
  ['other', 'Other'],
];

export function ScanPage() {
  const [file, setFile] = useState(null);
  const [viewType, setViewType] = useState('unspecified');
  const [categoryCode, setCategoryCode] = useState('');
  const [isAnalysing, setIsAnalysing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!file || isAnalysing) {
      return;
    }

    setIsAnalysing(true);
    setError(null);
    // Cleared so a previous verdict cannot sit on screen next to a new
    // photograph and be read as belonging to it.
    setResult(null);

    try {
      setResult(
        await analyseImage(file, {
          viewType,
          categoryCode: categoryCode.trim(),
        }),
      );
    } catch (cause) {
      setError(cause);
    } finally {
      setIsAnalysing(false);
    }
  }

  function handleReset() {
    setFile(null);
    setResult(null);
    setError(null);
    if (inputRef.current) {
      inputRef.current.value = '';
    }
  }

  return (
    <section className="page">
      <h1>Scan a package label</h1>
      <p>
        Upload a photograph of a packaged commodity label. The system reads the
        declarations it can find, checks them against the compliance rules
        loaded in this installation, and shows what it found and why.
      </p>

      <form className="panel" onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="scan-image">Label photograph</label>
          <input
            id="scan-image"
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setError(null);
            }}
          />
          {file && (
            <p className="panel__hint">
              {file.name} ({formatFileSize(file.size)})
            </p>
          )}
        </div>

        <div className="field">
          <label htmlFor="scan-view-type">Which panel is this?</label>
          <select
            id="scan-view-type"
            value={viewType}
            onChange={(event) => setViewType(event.target.value)}
          >
            {VIEW_TYPES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <p className="panel__hint">
            An absent declaration on a photograph of the front panel is not
            evidence the package lacks one.
          </p>
        </div>

        <div className="field">
          <label htmlFor="scan-category">Commodity category code (optional)</label>
          <input
            id="scan-category"
            type="text"
            value={categoryCode}
            placeholder="e.g. packaged-food"
            onChange={(event) => setCategoryCode(event.target.value)}
          />
          <p className="panel__hint">
            Determines which rules apply. Leave blank if unknown — the result
            will say the category was not known rather than assume one.
          </p>
        </div>

        <div className="field field--actions">
          <button type="submit" disabled={!file || isAnalysing}>
            {isAnalysing ? 'Analysing…' : 'Analyse label'}
          </button>
          <button type="button" onClick={handleReset} disabled={isAnalysing}>
            Clear
          </button>
        </div>
      </form>

      {isAnalysing && (
        <p className="panel" role="status">
          Reading the label and evaluating the applicable rules. This runs OCR
          on the image and usually takes a few seconds.
        </p>
      )}

      {error && (
        <div className="panel panel--error" role="alert">
          <p>
            <strong>The label could not be analysed.</strong> {error.message}
          </p>
          {error.details && (
            <ul>
              {Object.entries(error.details).map(([field, messages]) => (
                <li key={field}>
                  <strong>{field}:</strong>{' '}
                  {Array.isArray(messages) ? messages.join(' ') : String(messages)}
                </li>
              ))}
            </ul>
          )}
          {error.isNetworkError && (
            <p className="panel__hint">
              Start the Django server with{' '}
              <code>python backend/manage.py runserver</code>.
            </p>
          )}
        </div>
      )}

      {result && <ComplianceResultView result={result} />}
    </section>
  );
}

function ComplianceResultView({ result }) {
  const { extraction } = result;

  return (
    <section className="result" aria-label="Compliance result">
      <h2>Result</h2>

      <div className="panel">
        <p className="result__verdict">
          <StatusBadge
            value={result.result}
            tone={TONE_BY_RESULT[result.result] ?? 'neutral'}
          />
        </p>
        {/*
          The engine's own explanation. Never omit it: with zero rules loaded
          this is the sentence that says nothing was checked, and a verdict
          without it reads as a finding the system did not make.
        */}
        <p>{result.summary}</p>

        <dl className="status-list">
          <dt>Rules evaluated</dt>
          <dd>
            {result.rulesEvaluated} ({result.rulesPassed} passed,{' '}
            {result.rulesFailed} failed, {result.rulesInconclusive} undetermined)
          </dd>
          <dt>Commodity category</dt>
          <dd>{result.productCategoryCode ?? 'Not known'}</dd>
          <dt>Result id</dt>
          <dd>
            <code>{result.id}</code>
          </dd>
        </dl>
      </div>

      {result.result === 'review_required' && (
        <p className="panel panel--warning">
          <strong>Requires review.</strong> This is not a pass. It means the
          system could not responsibly reach a conclusion — because no rules
          applied, the commodity was not known, or the photograph could not be
          read — and a person needs to look at this label.
        </p>
      )}

      {extraction?.isPlaceholder && (
        <p className="panel panel--warning">
          <strong>No OCR engine is installed.</strong> The pipeline read no text
          from this image. Nothing shown below is a real reading.
        </p>
      )}

      <Findings violations={result.violations} />
      <ExtractionView extraction={extraction} />
    </section>
  );
}

function Findings({ violations }) {
  if (violations.length === 0) {
    return (
      <>
        <h3>Findings</h3>
        <p className="panel">
          No rule was found to have been broken. With no rules loaded this is
          the expected output and is not a finding of compliance.
        </p>
      </>
    );
  }

  return (
    <>
      <h3>Findings ({violations.length})</h3>
      {violations.map((violation) => (
        <div className="panel panel--error" key={violation.id}>
          <p>
            <strong>{violation.ruleCode}</strong>{' '}
            <StatusBadge value={violation.severity} tone="warning" />
          </p>
          <p>{violation.message}</p>
          {violation.legalReference && (
            <p className="panel__hint">
              Legal reference: {violation.legalReference}
            </p>
          )}
          {violation.evidence.map((item, index) =>
            item.excerpt ? (
              <blockquote key={index} className="evidence">
                {item.excerpt}
              </blockquote>
            ) : null,
          )}
        </div>
      ))}
    </>
  );
}

function ExtractionView({ extraction }) {
  if (!extraction) {
    return null;
  }

  return (
    <>
      <h3>What was read from the image</h3>

      <div className="panel">
        <dl className="status-list">
          <dt>Engine</dt>
          <dd>
            {extraction.engineName} {extraction.engineVersion}
          </dd>
          <dt>Extraction</dt>
          <dd>
            <StatusBadge
              value={extraction.status}
              tone={extraction.producedUsableOutput ? 'success' : 'warning'}
            />
          </dd>
          {extraction.processingMs !== null && (
            <>
              <dt>Time</dt>
              <dd>{extraction.processingMs} ms</dd>
            </>
          )}
        </dl>

        {extraction.errorMessage && (
          <p className="panel__hint">
            {humaniseCode(extraction.errorCode)}: {extraction.errorMessage}
          </p>
        )}
      </div>

      <h4>Declarations found ({extraction.fieldsRead.length})</h4>
      {extraction.fieldsRead.length === 0 ? (
        <p className="panel">
          No declaration was located in this image. That is not evidence the
          package lacks them — see the recognised text below for what was
          actually read.
        </p>
      ) : (
        <table className="fields-table">
          <thead>
            <tr>
              <th>Declaration</th>
              <th>Read as</th>
              <th>Normalised</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {extraction.fieldsRead.map((field) => (
              <tr key={field.fieldKey}>
                <td>{humaniseCode(field.fieldKey)}</td>
                <td>{field.rawValue}</td>
                <td>
                  {field.normalizedValue ? (
                    <code>{JSON.stringify(field.normalizedValue)}</code>
                  ) : (
                    '—'
                  )}
                  {field.normalizedValue?.uncertain && (
                    <> <StatusBadge value="uncertain" tone="warning" /></>
                  )}
                </td>
                {/* Null, never 0: an unreported confidence is not zero confidence. */}
                <td>
                  {field.confidence === null
                    ? '—'
                    : `${Math.round(field.confidence * 100)}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {extraction.unreadDeclarations.length > 0 && (
        <>
          <h4>Named but unreadable ({extraction.unreadDeclarations.length})</h4>
          <div className="panel panel--warning">
            <p>
              The label appears to name these declarations, but their values
              could not be read. This asks for a clearer photograph; it is not a
              finding that the declaration is missing.
            </p>
            <ul>
              {extraction.unreadDeclarations.map((item, index) => (
                <li key={index}>
                  <strong>{humaniseCode(item.fieldKey)}</strong> — read as{' '}
                  <q>{item.evidenceText}</q>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}

      <h4>Recognised text</h4>
      <pre className="recognised-text">
        {extraction.recognisedText || '(nothing was recognised)'}
      </pre>
    </>
  );
}
