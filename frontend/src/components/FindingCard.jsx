import { StatusBadge } from './StatusBadge.jsx';
import {
  formatConfidence,
  isUnrecognisedFindingStatus,
  needsEvidenceBeyondTheImage,
  reviewReasonsFor,
  toneForFindingStatus,
} from '../utils/compliance.js';
import { humaniseCode } from '../utils/format.js';

/**
 * One rule's outcome, laid out so a reviewer can check it by hand.
 *
 * A numbered marker matching the one drawn on the evidence image, the rule's
 * title, its outcome as a pill, and an inset block answering, in order: what
 * was required, which clause requires it, what was read, what the check made of
 * that, and what could not be established.
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
 * - **It does not invent evidence.** With no excerpt, the evidence line is
 *   absent - not filled with the message or with a placeholder quotation.
 * - **It does not invent review reasons.** Every reason under "Why this needs
 *   review" comes from `reviewReasonsFor`, which reads flags the response
 *   actually set. A plausible-sounding guess next to a legal outcome is worse
 *   than no explanation.
 * - **It does not present severity as legal weight.** It is a triage ranking
 *   copied from the rule, and it is labelled as one.
 * - **It does not present the AI's reading as authority.** The clause and the
 *   notification behind it are shown as the source; the message is the engine's
 *   explanation of a deterministic check, and the extracted value is labelled
 *   as something the OCR read.
 */
export function FindingCard({ finding, index }) {
  const tone = toneForFindingStatus(finding.status);
  const unrecognised = isUnrecognisedFindingStatus(finding.status);
  const confidence = formatConfidence(finding.extractedConfidence);
  const reviewReasons = reviewReasonsFor(finding);
  const notApplicable = finding.status === 'not_applicable';

  return (
    <article className={`finding finding--${tone}`}>
      <div className="finding__head">
        <span className="finding__index" aria-hidden="true">
          {String(index + 1).padStart(2, '0')}
        </span>

        <div className="finding__heading">
          <h4 className="finding__title">
            {/* A rule with no title still has a code, and the code is stable. */}
            {finding.title || finding.ruleCode}
          </h4>
          <p className="finding__rule">
            {finding.ruleCode}
            {finding.clause && ` · Rule ${finding.clause}`}
            {finding.checkType && ` · ${humaniseCode(finding.checkType)}`}
          </p>
        </div>

        <StatusBadge value={finding.status} tone={tone} />
      </div>

      <div className="finding__body">
        <p className="finding__message">{finding.message}</p>

        <dl className="detail-list">
          {finding.requirement && (
            <>
              <dt>Expected</dt>
              <dd>{finding.requirement}</dd>
            </>
          )}

          {finding.fieldKey && (
            <>
              <dt>Declaration</dt>
              <dd>{humaniseCode(finding.fieldKey)}</dd>
            </>
          )}

          {/*
            What the OCR read, kept apart from what the rule concluded. Absent
            rather than filled with a dash when nothing was read against this
            rule - an absence is the finding, and a row reading "—" invites it
            to be read as an empty declaration on the package.
          */}
          {finding.extractedRawValue && (
            <>
              <dt>Extracted value</dt>
              <dd>
                <span className="finding__value">
                  {finding.extractedRawValue}
                </span>
              </dd>
            </>
          )}

          {finding.extractedNormalizedValue && (
            <>
              <dt>Normalised</dt>
              <dd className="is-muted">
                {/*
                  The interpretation, beside the raw text and never instead of
                  it. Rendered as JSON because its shape differs per
                  declaration and inventing a prose rendering per shape would
                  be guessing at what the extractor meant.
                */}
                <code>{JSON.stringify(finding.extractedNormalizedValue)}</code>
              </dd>
            </>
          )}

          {/*
            The result is the badge in the heading, and it is deliberately not
            repeated here. A second copy of the same pill in the detail list
            reads as a second outcome, and it gives a reader two things to
            reconcile where there is only one verdict.
          */}

          {finding.legalReference && (
            <>
              <dt>Rule / clause</dt>
              <dd className="is-muted">{finding.legalReference}</dd>
            </>
          )}

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

          {finding.severity && (
            <>
              <dt>Severity</dt>
              <dd className="is-muted">
                {humaniseCode(finding.severity)} — triage ranking only, no legal
                weight
              </dd>
            </>
          )}

          <dt>Reading confidence</dt>
          {/*
            Null, never 0: an unreported confidence is not zero confidence, and
            an em dash is the only honest thing to draw for it.
          */}
          <dd className="is-muted">
            {confidence ?? '— not reported by the extraction engine'}
          </dd>
        </dl>

        {finding.evidenceExcerpt ? (
          <>
            <p className="finding__evidence-label">
              Evidence — text read from the photograph:
            </p>
            <blockquote className="evidence">{finding.evidenceExcerpt}</blockquote>
          </>
        ) : (
          <p className="hint">
            No text excerpt was recorded for this outcome.
          </p>
        )}

        {notApplicable && (
          <p className="finding__flag finding__flag--muted">
            <strong>This rule does not govern this package.</strong> Nothing
            about its declarations was examined, so this is not a pass. The
            explanation above says which fact excused it.
          </p>
        )}

        {reviewReasons.length > 0 && (
          <div className="finding__review" role="note">
            <p className="finding__review-heading">
              <strong>Why this needs review</strong>
            </p>
            <ul className="finding__review-list">
              {reviewReasons.map((reason) => (
                <li key={reason.label}>
                  {reason.label}
                  {reason.detail && <span className="is-muted"> — {reason.detail}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {needsEvidenceBeyondTheImage(finding) && (
          <p className="finding__flag">
            <strong>A photograph cannot settle this.</strong> The evidence this
            requirement needs is <code>{finding.detectionMethod}</code> — a
            physical measurement, a register, or a listing this system does not
            hold. Whatever is shown above, a person has to check it.
          </p>
        )}

        {finding.downgradedFromFailed && (
          <p className="finding__flag">
            <strong>Recorded as undetermined, not as a violation.</strong> This
            check did not pass, but the rule behind it has not been verified
            against the authoritative legal text, so the engine did not record a
            contravention. An unverified rule can flag a package for human
            review; it can never say a package breaks the law.
          </p>
        )}

        {unrecognised && (
          <p className="finding__flag">
            <strong>Unrecognised outcome “{String(finding.status)}”.</strong>{' '}
            This build does not know how to interpret it, and has not treated it
            as a pass.
          </p>
        )}

        {finding.applicabilityNote && (
          <details className="finding__applicability">
            <summary>Applicability — why this rule was applied</summary>
            {/*
              Rendered as text, never as markup. This is server-generated prose
              built from the legal framework, and the paragraph breaks it uses
              are the engine's own.
            */}
            {finding.applicabilityNote.split('\n\n').map((paragraph, position) => (
              <p key={position}>{paragraph}</p>
            ))}
          </details>
        )}

        {finding.violationId !== null && (
          <p className="hint">
            Recorded as violation #{finding.violationId} — listed under
            Violations below with its evidence.
          </p>
        )}
      </div>
    </article>
  );
}
