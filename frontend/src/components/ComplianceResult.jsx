import { Fragment } from 'react';

import { imagePositions } from '../utils/images.js';
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
 * `imageUrls`: the photographs exist in the browser that uploaded them and
 * nowhere else, and `EvidencePanel` says so rather than showing a broken frame.
 *
 * **One result, however many photographs.** An inspection may be made from up
 * to six, read together into one reading and judged once. This screen states
 * how many were checked and shows **one** verdict; a verdict per photograph
 * would describe an analysis the backend did not perform. Where a piece of
 * evidence was attributed to a particular photograph, the section that shows it
 * names that photograph - and where it was not, nothing is named rather than
 * the first one being assumed.
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
  imageUrls,
  onConfirmCategory,
  onConfirmFact,
  disabled = false,
}) {
  const images = result.images ?? [];
  const positions = imagePositions(images);
  const imageCount = images.length;

  return (
    <div className="result">
      <VerdictBanner result={result} />

      {/*
        Directly under the verdict, because "what was this judged from?" is the
        first thing a reader asks of an inspection with more than one
        photograph - and because it is the sentence that makes clear there is
        one result rather than several.
      */}
      {imageCount > 0 && (
        <p className="result__images" data-testid="images-checked">
          {imageCount === 1
            ? '1 image checked.'
            : `${imageCount} images checked — one package, one result.`}
          {images.some((entry) => entry.status === 'failed') && (
            <>
              {' '}
              Some photos could not be read; they are listed under{' '}
              <strong>Evidence from the photos</strong> below.
            </>
          )}
        </p>
      )}

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
        <ViolationsList
          violations={result.violations}
          imagePositions={positions}
        />
      </section>

      <section className="result__section">
        <h3 className="section-heading">
          {imageCount > 1 ? 'Evidence from the photos' : 'Evidence from the photo'}
        </h3>
        <p className="section-lede">
          {imageCount > 1
            ? 'The photos that were checked, with each finding outlined on the one it was read from.'
            : 'The photo that was checked, with the regions each finding was read from outlined on it.'}
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
            imageUrls={imageUrls}
            image={result.image}
            images={images}
            findings={result.findings}
            violations={result.violations}
            fieldsRead={result.extraction?.fieldsRead ?? []}
          />

          {/*
            How each photograph fared on its own. The run's status says whether
            the package was read well enough to judge against; this says whether
            an individual photograph contributed nothing - which is the
            difference between "retake this one" and "the whole thing was
            unreadable". Only worth a table when there is more than one.
          */}
          {imageCount > 1 && (
            <div className="card__body">
              <dl className="status-list">
                {images.map((entry) => (
                  <Fragment key={entry.image.id}>
                    <dt>{`Image ${entry.position}`}</dt>
                    <dd>{describeImageOutcome(entry)}</dd>
                  </Fragment>
                ))}
              </dl>
            </div>
          )}
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

/**
 * What became of one photograph, in the user's words.
 *
 * Reports this photograph's own `status`, which is not the run's: an inspection
 * can be `completed` - the label was read well enough to judge against - while
 * one of its photographs failed because it was too blurred to contribute.
 * Hiding the second would leave a submitter unable to see which one to retake.
 */
function describeImageOutcome(entry) {
  if (entry.status === 'failed') {
    return entry.errorCode
      ? `Could not be read (${entry.errorCode})`
      : 'Could not be read';
  }
  if (entry.status === 'empty') {
    return 'Read, but no text was recognised';
  }
  return 'Read';
}
