import { StatusBadge } from './StatusBadge.jsx';
import {
  formatConfidence,
  isUnrecognisedFindingStatus,
  toneForFindingStatus,
} from '../utils/compliance.js';
import { humaniseCode } from '../utils/format.js';

/**
 * One rule's outcome, laid out so a reviewer can check it by hand.
 *
 * The Figma finding row: a numbered marker matching the one drawn on the
 * evidence image, the rule's title, its outcome as a pill, and an inset block
 * of Requirement / Found / Regulation rows.
 *
 * What this component will not do:
 *
 * - **It does not re-decide anything.** `status` is rendered as it arrived.
 *   `inconclusive` is drawn in its own tone, never as a muted pass; an
 *   unrecognised status is drawn neutrally and labelled as unrecognised.
 * - **It does not threshold the confidence.** `extractedConfidence` is shown
 *   because a reader deserves to know what the reading behind a finding was
 *   worth. It is informational: no rule in this system conditions its outcome
 *   on it, and a low number does not weaken a `passed`.
 * - **It does not invent evidence.** With no excerpt, the evidence line is
 *   absent - not filled with the message or with a placeholder quotation.
 * - **It does not present severity as legal weight.** It is a triage ranking
 *   copied from the rule, and it is labelled as one.
 */
export function FindingCard({ finding, index }) {
  const tone = toneForFindingStatus(finding.status);
  const unrecognised = isUnrecognisedFindingStatus(finding.status);
  const confidence = formatConfidence(finding.extractedConfidence);

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
            {finding.checkType && ` · ${humaniseCode(finding.checkType)}`}
            {finding.fieldKey && ` · ${humaniseCode(finding.fieldKey)}`}
          </p>
        </div>

        <StatusBadge value={finding.status} tone={tone} />
      </div>

      <div className="finding__body">
        <p className="finding__message">{finding.message}</p>

        <dl className="detail-list">
          {finding.requirement && (
            <>
              <dt>Requirement</dt>
              <dd>{finding.requirement}</dd>
            </>
          )}

          {finding.fieldKey && (
            <>
              <dt>Declaration</dt>
              <dd>{humaniseCode(finding.fieldKey)}</dd>
            </>
          )}

          {finding.legalReference && (
            <>
              <dt>Regulation</dt>
              <dd className="is-muted">{finding.legalReference}</dd>
            </>
          )}

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
          <blockquote className="evidence">{finding.evidenceExcerpt}</blockquote>
        ) : (
          <p className="hint">
            No text excerpt was recorded for this outcome.
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
