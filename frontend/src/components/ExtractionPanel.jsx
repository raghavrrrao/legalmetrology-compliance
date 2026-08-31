import { StatusBadge } from './StatusBadge.jsx';
import { formatConfidence } from '../utils/compliance.js';
import { humaniseCode } from '../utils/format.js';

/**
 * "Extracted Data": what the pipeline read off the label.
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
 */
export function ExtractionPanel({ extraction }) {
  if (!extraction) {
    return null;
  }

  return (
    <>
      <div className="card">
        <div className="card__header">
          <h3 className="card__title">
            <span aria-hidden="true">{'{ }'}</span> Extracted data
          </h3>
          <span className="verdict__meta">
            {extraction.engineName} {extraction.engineVersion}
          </span>
        </div>

        <div className="card__body">
          <dl className="status-list">
            <dt>Extraction</dt>
            <dd>
              <StatusBadge
                value={extraction.status}
                tone={extraction.producedUsableOutput ? 'success' : 'warning'}
              />
            </dd>
            <dt>Usable reading</dt>
            <dd>
              {extraction.producedUsableOutput
                ? 'Yes — the label was read well enough to be checked against.'
                : 'No — an absent declaration here says nothing about the package.'}
            </dd>
            {extraction.processingMs !== null && (
              <>
                <dt>Time</dt>
                <dd>{extraction.processingMs} ms</dd>
              </>
            )}
          </dl>

          {extraction.errorMessage && (
            <p className="hint">
              {humaniseCode(extraction.errorCode)}: {extraction.errorMessage}
            </p>
          )}
        </div>

        {extraction.fieldsRead.length === 0 ? (
          <div className="card__body">
            <div className="empty-state">
              <p>
                No declaration was located in this image. That is not evidence
                the package lacks them — see the recognised text below for what
                was actually read.
              </p>
            </div>
          </div>
        ) : (
          <div className="table-scroll">
            <table className="fields-table">
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Value read</th>
                  <th scope="col">Normalised</th>
                  <th scope="col">Conf.</th>
                </tr>
              </thead>
              <tbody>
                {extraction.fieldsRead.map((field) => (
                  <tr key={field.fieldKey}>
                    <th scope="row">{humaniseCode(field.fieldKey)}</th>
                    <td>{field.rawValue}</td>
                    <td>
                      {field.normalizedValue ? (
                        <code>{JSON.stringify(field.normalizedValue)}</code>
                      ) : (
                        '—'
                      )}
                      {field.normalizedValue?.uncertain && (
                        <>
                          {' '}
                          <StatusBadge value="uncertain" tone="warning" />
                        </>
                      )}
                    </td>
                    {/* Null, never 0: an unreported confidence is not zero. */}
                    <td className="is-numeric">
                      {formatConfidence(field.confidence) ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="card__footer">
          <span>
            Confidence is what the extraction engine reported about its own
            reading. It is informational and does not affect any outcome.
          </span>
        </div>
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
        </div>
      )}

      <div className="card">
        <div className="card__header">
          <h3 className="card__title">Recognised text</h3>
        </div>
        <div className="card__body">
          <pre className="recognised-text">
            {extraction.recognisedText || '(nothing was recognised)'}
          </pre>
        </div>
      </div>
    </>
  );
}
