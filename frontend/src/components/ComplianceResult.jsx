import { ApplicabilityAssessment } from './ApplicabilityAssessment.jsx';
import { DeclarationsPanel } from './DeclarationsPanel.jsx';
import { EvidencePanel } from './EvidencePanel.jsx';
import { ExtractionPanel } from './ExtractionPanel.jsx';
import { FindingsList } from './FindingsList.jsx';
import { VerdictBanner } from './VerdictBanner.jsx';
import { ViolationsList } from './ViolationsList.jsx';

/**
 * The compliance assessment screen body.
 *
 * Shared by the scan flow and by a result opened from a link, so a permalinked
 * result is the same screen and not a lesser copy of it. The only difference is
 * `imageUrl`: the photograph exists in the browser that uploaded it and nowhere
 * else, and `EvidencePanel` says so rather than showing a broken frame.
 *
 * **The verdict is the first screenful, alone.** It used to share the top of the
 * screen with the evidence image in a two-column layout, which meant the
 * outcome — the one thing every reader is here for — competed with a photograph
 * for the first glance and lost it on a narrow window. The order now is the
 * order of the questions a reader asks:
 *
 *     What was concluded?      the verdict and its counts
 *     On what requirements?    the findings, failures first
 *     What is wrong?           the violations of record
 *     From what evidence?      the photo, with the regions marked
 *     What was read?           the extraction
 *     What was stated?         the declarations
 *
 * Three kinds of evidence appear here and each keeps its own heading, in its own
 * words:
 *
 *     Extraction    what the pipeline READ off the photograph
 *     Declarations  what a person SAID about the goods
 *     Findings      what the rules CONCLUDED from both
 *
 * A submitter's assertion that a package contains bidi is not a measurement,
 * and a screen that listed it beside the extracted net quantity would present
 * it as one.
 */
export function ComplianceResult({
  result,
  imageUrl,
  onConfirmCategory,
  onConfirmFact,
  disabled = false,
}) {
  return (
    <div className="result">
      <VerdictBanner result={result} />

      {/*
        Directly under the verdict, because it says what chose the rule set.
        A reader must not get to the findings without knowing whether a person
        or the label classifier decided which requirements were checked - and,
        when nothing decided it, that the type is still to be confirmed.
      */}
      <ApplicabilityAssessment
        assessment={result.applicabilityAssessment}
        disabled={disabled}
        onConfirmCategory={onConfirmCategory}
        onConfirmFact={onConfirmFact}
      />

      {result.extraction?.isPlaceholder && (
        <p className="panel panel--warning">
          <strong>No text reader is installed on this server.</strong> The
          pipeline read no text from this photo. Nothing shown here is a real
          reading.
        </p>
      )}

      <section className="result__section">
        <h3 className="section-heading">
          Requirements checked
          {result.findingsReported && ` (${result.findings.length})`}
        </h3>
        <p className="section-lede">
          Every requirement that was examined, and what each one concluded.
          Failures first, then the ones needing review.
        </p>
        <FindingsList
          findings={result.findings}
          findingsReported={result.findingsReported}
        />
      </section>

      <section className="result__section">
        <h3 className="section-heading">
          Violations recorded ({result.violations.length})
        </h3>
        <p className="section-lede">
          What this package was found to fail, with the evidence behind each.
        </p>
        <ViolationsList violations={result.violations} />
      </section>

      <section className="result__section">
        <h3 className="section-heading">Evidence from the photo</h3>
        <p className="section-lede">
          The photo that was checked, with the regions each finding was read
          from outlined on it.
        </p>
        <div className="card">
          <div className="card__header">
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
      </section>

      <section className="result__section">
        <ExtractionPanel extraction={result.extraction} />
      </section>

      <section className="result__section">
        <DeclarationsPanel declarations={result.applicabilityDeclarations} />
      </section>

      <div className="card">
        <div className="card__body">
          <dl className="status-list">
            <dt>Product type</dt>
            <dd>{result.productCategoryCode ?? 'Not known'}</dd>
            <dt>Result id</dt>
            <dd>
              <code>{result.id}</code>
            </dd>
          </dl>
        </div>
      </div>
    </div>
  );
}
