import { EvidencePanel } from './EvidencePanel.jsx';
import { ExtractionPanel } from './ExtractionPanel.jsx';
import { FindingsList } from './FindingsList.jsx';
import { VerdictBanner } from './VerdictBanner.jsx';
import { ViolationsList } from './ViolationsList.jsx';

/**
 * The Figma "Compliance Assessment" screen body.
 *
 * Two columns on a wide viewport - evidence on the left, verdict and findings
 * on the right - collapsing to one on a narrow one, which is the mobile screen's
 * order: verdict, evidence, findings, extracted data.
 *
 * Shared by the scan flow and by a result opened from a link, so a permalinked
 * result is the same screen and not a lesser copy of it. The only difference is
 * `imageUrl`: the photograph exists in the browser that uploaded it and nowhere
 * else, and `EvidencePanel` says so rather than showing a broken frame.
 *
 * The section order is deliberate. What was concluded comes first, what it was
 * concluded from comes second, and what was read off the label comes last and
 * under its own heading - because a reading and a verdict are different claims
 * and a screen that runs them together invites the first to be read as the
 * second.
 */
export function ComplianceResult({ result, imageUrl }) {
  return (
    <div className="result-layout">
      <div className="result-layout__evidence">
        <div className="card">
          <div className="card__header">
            <h2 className="card__title">
              <span aria-hidden="true">▤</span> Evidence
            </h2>
            <span className="verdict__meta">
              {result.image
                ? `${result.image.imageFormat?.toUpperCase()} · ${result.image.width}×${result.image.height}`
                : 'No image on record'}
            </span>
          </div>
          <EvidencePanel
            imageUrl={imageUrl}
            image={result.image}
            findings={result.findings}
          />
        </div>

        <h3 className="section-heading">Extraction — what was read</h3>
        <ExtractionPanel extraction={result.extraction} />
      </div>

      <div className="result-layout__findings">
        <VerdictBanner result={result} />

        {result.extraction?.isPlaceholder && (
          <p className="panel panel--warning">
            <strong>No OCR engine is installed.</strong> The pipeline read no
            text from this image. Nothing shown here is a real reading.
          </p>
        )}

        <h3 className="section-heading">
          Key findings — what was checked
          {result.findingsReported && ` (${result.findings.length})`}
        </h3>
        <FindingsList
          findings={result.findings}
          findingsReported={result.findingsReported}
        />

        <h3 className="section-heading">
          Violations — what the package failed ({result.violations.length})
        </h3>
        <ViolationsList violations={result.violations} />

        <div className="card">
          <div className="card__body">
            <dl className="status-list">
              <dt>Commodity category</dt>
              <dd>{result.productCategoryCode ?? 'Not known'}</dd>
              <dt>Result id</dt>
              <dd>
                <code>{result.id}</code>
              </dd>
            </dl>
          </div>
        </div>
      </div>
    </div>
  );
}
