import { StatusBadge } from './StatusBadge.jsx';
import { formatConfidence } from '../utils/compliance.js';
import { humaniseCode } from '../utils/format.js';
import { imageLabel, imagePositions } from '../utils/images.js';

/**
 * What the pipeline read off the label.
 *
 * Kept visually and textually distinct from the compliance result, because they
 * answer different questions and collapsing them is the mistake this screen
 * exists to avoid:
 *
 *     Extraction  - what was detected on the package?
 *     Compliance  - what do the rules make of those values?
 *
 * Nothing in this panel carries a verdict, and none of its badges uses the
 * verdict vocabulary. `status` here is the run's own lifecycle
 * (completed / empty / failed), and its tone comes from
 * `producedUsableOutput` - whether the label was read well enough to be judged
 * against at all - not from anything a rule concluded.
 *
 * **A declaration may legitimately appear twice.** An inspection can carry
 * several photographs, and a declaration printed on two photographed panels is
 * read once per panel. Both readings are listed, each against the photograph it
 * came from, because both are real observations - and deciding which panel of a
 * package to believe is not this browser's job. Which one the rule engine
 * judged against is the backend's answer, on the finding.
 *
 * **The meaningful fields come first; the raw recognised text is a disclosure.**
 * The OCR dump is genuinely useful — it is how somebody checks a reading that
 * looks wrong — but it is a wall of broken words, and printed in full above the
 * fields it swamped the one thing a reader wanted, which was "what did it
 * actually find?". Nothing is removed; the order is what changed.
 */
export function ExtractionPanel({ extraction }) {
  if (!extraction) {
    return null;
  }

  // Named only when there is more than one photograph to tell apart; with a
  // single one "Image 1" is noise. `imageLabel` enforces that itself.
  const positions = imagePositions(extraction.images ?? []);

  return (
    <>
      <div className="card">
        <div className="card__header">
          <h3 className="card__title">Label information</h3>
          <span className="verdict__meta">
            {extraction.engineName} {extraction.engineVersion}
          </span>
        </div>

        {extraction.fieldsRead.length === 0 ? (
          <div className="card__body">
            <div className="empty-state">
              <p>
                No declaration was located in this photo. That is not evidence
                the package lacks them — open the recognised text below to see
                what was actually read.
              </p>
            </div>
          </div>
        ) : (
          <ul className="read-fields" aria-label="What we read from the label">
            {extraction.fieldsRead.map((field, index) => (
              // Keyed by index as well as by field key: the same declaration
              // can be read off two panels, and two <li>s with one key is a
              // React collision that silently drops the second.
              <li className="read-field" key={`${field.fieldKey}-${index}`}>
                <span className="read-field__name">
                  {humaniseCode(field.fieldKey)}
                  {imageLabel(field.imageId, positions) && (
                    <span className="read-field__source">
                      {` · ${imageLabel(field.imageId, positions)}`}
                    </span>
                  )}
                </span>
                <span className="read-field__value">{field.rawValue}</span>
                {field.normalizedValue?.uncertain && (
                  <span className="read-field__warning">
                    <span aria-hidden="true">&#9888;</span> Uncertain reading —
                    the text reader would not commit to an interpretation of
                    this. It is shown as read.
                  </span>
                )}
                <span className="read-field__meta is-muted">
                  {formatConfidence(field.confidence)
                    ? `Reader confidence ${formatConfidence(field.confidence)}`
                    : 'Confidence not reported'}
                  {/*
                    The extractor's interpretation, beside the raw text and
                    never instead of it. Rendered as JSON because its shape
                    differs per declaration, and inventing a prose rendering
                    per shape would be guessing at what the extractor meant.
                  */}
                  {field.normalizedValue && (
                    <>
                      {' · normalised: '}
                      <code>{JSON.stringify(field.normalizedValue)}</code>
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className="card__body">
          <p className="hint">
            {extraction.producedUsableOutput
              ? 'The label was read well enough to be checked against.'
              : 'The label could not be read usefully. A declaration missing from this reading says nothing about the package.'}
          </p>
          {extraction.errorMessage && (
            <p className="hint">
              {humaniseCode(extraction.errorCode)}: {extraction.errorMessage}
            </p>
          )}
        </div>

        <details className="technical-details technical-details--card">
          <summary>View extracted text</summary>

          <dl className="detail-list">
            <dt>Reading status</dt>
            <dd>
              <StatusBadge
                value={extraction.status}
                tone={extraction.producedUsableOutput ? 'success' : 'warning'}
              />
            </dd>
            <dt>Text reader</dt>
            <dd>
              {extraction.engineName} {extraction.engineVersion}
            </dd>
            {extraction.processingMs !== null && (
              <>
                <dt>Time</dt>
                <dd>{extraction.processingMs} ms</dd>
              </>
            )}
          </dl>

          {/*
            The fields are not repeated here. They are above, in full, with
            their normalised values and confidences beside them; a second copy
            in a table would be the same facts twice, and a reader who found a
            discrepancy between the two would have no way to tell which was the
            reading. What this disclosure adds is the thing the list cannot
            show: the unstructured text the fields were pulled out of.
          */}
          <p className="finding__block-title">Recognised text</p>
          <pre className="recognised-text">
            {extraction.recognisedText || '(nothing was recognised)'}
          </pre>

          <p className="hint">
            Confidence is what the text reader reported about its own reading.
            It is informational and does not affect any outcome.
          </p>
        </details>
      </div>

      {extraction.unreadDeclarations.length > 0 && (
        <div className="card">
          <div className="card__header">
            <h3 className="card__title">
              Named but unreadable ({extraction.unreadDeclarations.length})
            </h3>
          </div>
          <div className="card__body">
            <p className="finding__message">
              The label appears to name these declarations, but their values
              could not be read. This asks for a clearer photo; it is not a
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
        </div>
      )}
    </>
  );
}
