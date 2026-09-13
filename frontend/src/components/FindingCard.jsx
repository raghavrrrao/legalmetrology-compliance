import {
  formatConfidence,
  isUnrecognisedFindingStatus,
  needsEvidenceBeyondTheImage,
  reviewReasonsFor,
  toneForFindingStatus,
} from '../utils/compliance.js';
import { humaniseCode } from '../utils/format.js';

/**
 * One requirement's outcome: scannable at a glance, verifiable on demand.
 *
 * A reader with eight findings in front of them is triaging, not studying. The
 * closed card carries what triage needs and nothing else: the status, the
 * requirement's name, its clause, the engine's one-sentence explanation, and
 * **what was expected beside what was found** — the two values the reader is
 * actually comparing. Behind "Details" sits what a reviewer needs to *verify*
 * that comparison: the normalised reading, the legal reference and source, the
 * severity, the confidence, and why the requirement was applied at all.
 *
 * Three things refuse to be hidden, because hiding them would change what the
 * card says:
 *
 * - **Why a review is needed**, with what the user can do about it. A
 *   `requires review` whose reason is one click away reads as a soft failure.
 * - **The flags** that qualify the status: a requirement a photograph cannot
 *   settle, a failure downgraded because its rule is unverified, an
 *   unrecognised status. Each of those is a caveat *on the outcome itself*.
 *
 * What this component will not do:
 *
 * - **It does not re-decide anything.** `status` is rendered as it arrived.
 *   `inconclusive` is drawn in its own tone, never as a muted pass;
 *   `not_applicable` is drawn as its own thing, never as a pass either; an
 *   unrecognised status is drawn neutrally and labelled as unrecognised.
 * - **It does not threshold the confidence.** `extractedConfidence` is shown
 *   because a reader deserves to know what the reading behind a finding was
 *   worth. It is informational: no rule in this system conditions its outcome
 *   on it, and a low number does not weaken a `passed`.
 * - **It does not invent evidence.** With no excerpt, the evidence disclosure
 *   is absent - not filled with the message or with a placeholder quotation.
 * - **It does not invent review reasons.** Every reason comes from
 *   `reviewReasonsFor`, which reads flags the response actually set. A
 *   plausible-sounding guess next to a legal outcome is worse than no
 *   explanation.
 * - **It does not present severity as legal weight.** It is a triage ranking
 *   copied from the rule, and it is labelled as one.
 */
export function FindingCard({ finding, index }) {
  const tone = toneForFindingStatus(finding.status);
  const unrecognised = isUnrecognisedFindingStatus(finding.status);
  const confidence = formatConfidence(finding.extractedConfidence);
  const reviewReasons = reviewReasonsFor(finding);
  const notApplicable = finding.status === 'not_applicable';

  return (
    <article className={`finding finding--${tone}`}>
      <header className="finding__head">
        <span className={`finding__badge finding__badge--${tone}`}>
          <StatusIcon status={finding.status} />
          {STATUS_LABEL[finding.status] ?? humaniseCode(finding.status)}
        </span>
        <span className="finding__index" aria-hidden="true">
          {String(index + 1).padStart(2, '0')}
        </span>
      </header>

      <div className="finding__body">
        <h4 className="finding__title">
          {/* A rule with no title still has a code, and the code is stable. */}
          {finding.title || finding.ruleCode}
        </h4>
        {finding.clause && (
          <p className="finding__rule">Rule {finding.clause}</p>
        )}

        <p className="finding__message">{finding.message}</p>

        {/*
          Expected beside found, on the face of the card. These are the two
          values a reviewer is comparing; behind a disclosure they cost a click
          per finding, and eight findings means eight clicks to answer the
          question the page exists to answer.
        */}
        <dl className="finding__facts">
          {finding.requirement && (
            <div className="finding__fact">
              <dt>Expected</dt>
              <dd>{finding.requirement}</dd>
            </div>
          )}
          <div className="finding__fact">
            <dt>Found</dt>
            <dd>
              {finding.extractedRawValue ? (
                <span className="finding__value">
                  {finding.extractedRawValue}
                </span>
              ) : (
                /*
                  An absence is the finding here, and it must not be dressed up
                  as a value - nor stated more strongly than the evidence
                  allows. What is known is that nothing was detected in this
                  photo, not that the package lacks the declaration.
                */
                <span className="is-muted">
                  Not detected in this photo
                </span>
              )}
            </dd>
          </div>
        </dl>

        {reviewReasons.length > 0 && (
          <div className="finding__review" role="note">
            <h5 className="finding__review-heading">Why can’t we decide?</h5>
            <ul className="finding__review-list">
              {reviewReasons.map((reason) => (
                <li key={reason.label}>
                  {reason.label}
                  {reason.detail && (
                    <span className="is-muted"> — {reason.detail}</span>
                  )}
                </li>
              ))}
            </ul>
            {/*
              Only offered when it is true. An unstated fact is something the
              user can go and state; a reading a photograph cannot settle is
              not, and telling them to answer a question would send them in a
              circle. Read from the same response flags as the reasons above.
            */}
            {hasUnstatedFact(finding) && (
              <p className="finding__review-action">
                <strong>What you can do:</strong> answer that question under
                “Tell us about this package” and check the same reading again.
                The photo is not uploaded or read a second time.
              </p>
            )}
          </div>
        )}

        {notApplicable && (
          <p className="finding__flag finding__flag--muted">
            <strong>This requirement does not govern this package.</strong>{' '}
            Nothing about its declarations was examined, so this is not a pass.
            The explanation above says which fact excused it.
          </p>
        )}

        {needsEvidenceBeyondTheImage(finding) && (
          <p className="finding__flag">
            <strong>A photo cannot settle this.</strong> The evidence this
            requirement needs is <code>{finding.detectionMethod}</code> — a
            physical measurement, a register, or a listing this system does not
            hold. Whatever is shown here, a person has to check it.
          </p>
        )}

        {finding.downgradedFromFailed && (
          <p className="finding__flag">
            <strong>Recorded as requiring review, not as a violation.</strong>{' '}
            This check did not pass, but the rule behind it has not been
            verified against the authoritative legal text, so the engine did not
            record a contravention. An unverified rule can flag a package for
            human review; it can never say a package breaks the law.
          </p>
        )}

        {unrecognised && (
          <p className="finding__flag">
            <strong>Unrecognised outcome “{String(finding.status)}”.</strong>{' '}
            This build does not know how to interpret it, and has not treated it
            as a pass.
          </p>
        )}

        <div className="finding__disclosures">
          {finding.evidenceExcerpt && (
            <details className="finding__details">
              <summary>View evidence</summary>
              <p className="finding__evidence-label">
                Text read from the photo:
              </p>
              <blockquote className="evidence">
                {finding.evidenceExcerpt}
              </blockquote>
            </details>
          )}

          <details className="finding__details">
            <summary>Details</summary>

            <dl className="detail-list">
              {/*
                Expected and found are on the card itself, above. Repeating
                them here would give a reader two copies to reconcile and no
                way to tell which was the reading.
              */}
              {finding.extractedNormalizedValue && (
                <>
                  <dt>Normalised reading</dt>
                  <dd className="is-muted">
                    {/*
                      The interpretation, beside the raw text and never instead
                      of it. Rendered as JSON because its shape differs per
                      declaration and inventing a prose rendering per shape
                      would be guessing at what the extractor meant.
                    */}
                    <code>
                      {JSON.stringify(finding.extractedNormalizedValue)}
                    </code>
                  </dd>
                </>
              )}

              {finding.legalReference && (
                <>
                  <dt>Legal reference</dt>
                  <dd className="is-muted">{finding.legalReference}</dd>
                </>
              )}

              <dt>Rule code</dt>
              <dd className="is-muted">
                <code>{finding.ruleCode}</code>
                {finding.checkType && ` · ${humaniseCode(finding.checkType)}`}
              </dd>

              <dt>Source</dt>
              <dd className="is-muted">
                {finding.legalSourceCitation ? (
                  <>
                    {finding.legalSourceCitation} — the notification that last
                    amended this clause in the loaded framework.
                  </>
                ) : (
                  'No amending notification is recorded for this clause in the loaded framework.'
                )}
              </dd>

              {finding.fieldKey && (
                <>
                  <dt>Declaration</dt>
                  <dd className="is-muted">{humaniseCode(finding.fieldKey)}</dd>
                </>
              )}

              {finding.severity && (
                <>
                  <dt>Severity</dt>
                  <dd className="is-muted">
                    {humaniseCode(finding.severity)} — triage ranking only, no
                    legal weight
                  </dd>
                </>
              )}

              <dt>Reading confidence</dt>
              {/*
                Null, never 0: an unreported confidence is not zero confidence,
                and an em dash is the only honest thing to draw for it. This is
                what the text reader thought of its own reading; it is not a
                confidence in the compliance outcome, and the wording says so.
              */}
              <dd className="is-muted">
                {confidence
                  ? `${confidence} — the text reader's confidence in what it read, not in this outcome`
                  : '— not reported by the extraction engine'}
              </dd>

              {finding.violationId !== null && (
                <>
                  <dt>Violation record</dt>
                  <dd className="is-muted">
                    #{finding.violationId} — listed under Violations with its
                    evidence.
                  </dd>
                </>
              )}
            </dl>

            {finding.applicabilityNote && (
              <>
                <h5 className="finding__block-title">
                  Why this requirement was applied
                </h5>
                {/*
                  Rendered as text, never as markup. This is server-generated
                  prose built from the legal framework, and the paragraph breaks
                  it uses are the engine's own.
                */}
                {finding.applicabilityNote
                  .split('\n\n')
                  .map((paragraph, position) => (
                    <p key={position}>{paragraph}</p>
                  ))}
              </>
            )}
          </details>
        </div>
      </div>
    </article>
  );
}

/**
 * The four statuses in the user's words, with a mark that is not a colour.
 *
 * Partial on purpose, like every other lookup over a backend vocabulary in this
 * app: a status added to the API after this build shipped falls through to the
 * humanised raw value and the neutral question mark, rather than inheriting the
 * appearance of whichever entry happened to be first.
 */
const STATUS_LABEL = Object.freeze({
  passed: 'Passed',
  failed: 'Failed',
  inconclusive: 'Requires review',
  not_applicable: 'Not applicable',
});

/**
 * The status mark, drawn.
 *
 * `aria-hidden`, and never the only carrier of the status: the badge says the
 * word beside it, so the outcome survives a failed icon, a high-contrast mode
 * and a monochrome printout. An unrecognised status gets the question mark,
 * which is the honest glyph for one.
 */
function StatusIcon({ status }) {
  const paths = {
    passed: <path d="m3.5 8.5 3 3 6-7" />,
    failed: <path d="M8 3.5v5.5M8 12.2v.3" />,
    inconclusive: (
      <path d="M5.8 6a2.2 2.2 0 1 1 2.9 2.1c-.5.2-.7.6-.7 1.1v.4M8 12.2v.3" />
    ),
    not_applicable: <path d="M4 8h8" />,
  };

  return (
    <span className="finding__badge-mark" aria-hidden="true">
      <svg
        viewBox="0 0 16 16"
        width="12"
        height="12"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {paths[status] ?? paths.inconclusive}
      </svg>
    </span>
  );
}

/**
 * True when a review is waiting on a fact the submitter could simply state.
 *
 * Read from the same response field the review reason is built from
 * (`details.unresolved_conditions`), so the offer to go and answer a question
 * appears exactly when there is a question to answer.
 */
function hasUnstatedFact(finding) {
  const unresolved = finding?.details?.unresolved_conditions;
  return Array.isArray(unresolved) && unresolved.length > 0;
}
