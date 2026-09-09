/**
 * Presentation helpers for compliance data.
 *
 * **This file makes no compliance decision and must never be allowed to.**
 * Everything here answers one of two questions - "what colour is this status?"
 * and "what order should these appear in?" - from a value the backend already
 * decided. Nothing derives a verdict, combines statuses, thresholds a
 * confidence, or infers an outcome the response did not state.
 *
 * The lookups are deliberately partial and every caller falls back to a neutral
 * tone. A status this file has never heard of - a value added to the API after
 * this build shipped - must render as unrecognised, not inherit the appearance
 * of whichever entry happened to be the default. Rendering an unknown status in
 * green is the specific failure this shape prevents.
 */

/** Verdicts this build knows how to present. */
export const KNOWN_RESULTS = Object.freeze([
  'compliant',
  'partially_compliant',
  'non_compliant',
  'review_required',
]);

/**
 * Finding outcomes this build knows how to present.
 *
 * Four, and the last two are the ones that matter. `inconclusive` means the
 * check could not be decided; `not_applicable` means the rule does not govern
 * this package, so nothing about its declarations was examined. Neither is a
 * pass, and a client that renders either as one is making a claim the engine
 * refused to make.
 */
export const KNOWN_FINDING_STATUSES = Object.freeze([
  'passed',
  'failed',
  'inconclusive',
  'not_applicable',
]);

const TONE_BY_RESULT = Object.freeze({
  compliant: 'success',
  partially_compliant: 'warning',
  non_compliant: 'error',
  // Not 'success' and not 'error'. It means a person needs to look at this.
  review_required: 'review',
});

const TONE_BY_FINDING_STATUS = Object.freeze({
  passed: 'success',
  failed: 'error',
  inconclusive: 'review',
  // Not 'success'. Nothing was checked, so there is nothing to be green about,
  // and a reviewer scanning the list must be able to tell an exemption from a
  // pass at a glance.
  not_applicable: 'muted',
});

/**
 * How the finding statuses are ordered on screen: the ones a reviewer has to
 * act on first, then the ones that could not be decided, then the passes.
 *
 * Ordering only. It changes what a user reads first, never what a rule
 * concluded, and an unknown status sorts to the front rather than being buried.
 */
const FINDING_STATUS_ORDER = Object.freeze({
  failed: 0,
  inconclusive: 1,
  passed: 2,
  // Last: nothing was examined, so there is nothing here for a reviewer to
  // check. It is still listed, because "this rule did not apply to you" is
  // part of understanding the result.
  not_applicable: 3,
});

/** @returns {'success'|'warning'|'error'|'review'|'neutral'} */
export function toneForResult(result) {
  return TONE_BY_RESULT[result] ?? 'neutral';
}

/** @returns {'success'|'error'|'review'|'muted'|'neutral'} */
export function toneForFindingStatus(status) {
  return TONE_BY_FINDING_STATUS[status] ?? 'neutral';
}

/** True when the API returned a verdict this build does not know how to show. */
export function isUnrecognisedResult(result) {
  return !KNOWN_RESULTS.includes(result);
}

/** True when the API returned a finding status this build does not know. */
export function isUnrecognisedFindingStatus(status) {
  return !KNOWN_FINDING_STATUSES.includes(status);
}

/**
 * Findings sorted for reading, without mutating the caller's array.
 *
 * Ties keep the order the API sent, which is `rule_code` - so two failures
 * always appear in the same sequence for the same result.
 */
export function sortFindingsForDisplay(findings) {
  return [...findings].sort((a, b) => {
    const left = FINDING_STATUS_ORDER[a.status] ?? -1;
    const right = FINDING_STATUS_ORDER[b.status] ?? -1;
    return left - right;
  });
}

/**
 * A confidence in [0, 1] as a percentage string, or null.
 *
 * Null in, null out - and the caller renders an em dash. An unreported
 * confidence is not zero confidence, and must never be shown as "0%".
 */
export function formatConfidence(confidence) {
  if (typeof confidence !== 'number' || Number.isNaN(confidence)) {
    return null;
  }
  return `${Math.round(confidence * 100)}%`;
}

/**
 * A bounding box as CSS percentages of the source image, or null.
 *
 * The box arrives in source-image pixels; `width` and `height` are the source
 * dimensions the backend measured from the bytes. Expressing the result in
 * percentages means the overlay stays aligned at whatever size the image is
 * displayed, with no measurement in JavaScript.
 *
 * Returns null for anything that is not a usable box rather than guessing at
 * missing numbers. Coordinates are never invented: an unusable box is drawn as
 * no box at all, and the finding still shows its excerpt.
 */
export function boundingBoxToPercentages(box, imageWidth, imageHeight) {
  if (!box || !Number.isFinite(imageWidth) || !Number.isFinite(imageHeight)) {
    return null;
  }
  if (imageWidth <= 0 || imageHeight <= 0) {
    return null;
  }

  const { x, y, width, height } = box;
  const numbers = [x, y, width, height];
  if (!numbers.every((value) => typeof value === 'number' && Number.isFinite(value))) {
    return null;
  }
  if (width <= 0 || height <= 0) {
    return null;
  }

  return {
    left: `${(x / imageWidth) * 100}%`,
    top: `${(y / imageHeight) * 100}%`,
    width: `${(width / imageWidth) * 100}%`,
    height: `${(height / imageHeight) * 100}%`,
  };
}

/**
 * Detection methods that a photograph could, in principle, settle.
 *
 * Everything else on `ComplianceFinding.detection_method` names evidence this
 * pipeline does not have - a physical weighing, a regulator's register, an
 * e-commerce listing - and a finding carrying one of those needs a human
 * whatever its status reads. The list is short and closed because it describes
 * *this* pipeline's inputs, not a legal category.
 */
const IMAGE_EVALUABLE_METHODS = Object.freeze(['ocr', 'cv', 'ocr_cv']);

/**
 * True when settling this finding needed evidence a photograph cannot carry.
 *
 * An empty `detectionMethod` is not treated as "needs a human": the field is
 * blank when the rule is not mapped to the legal framework, which says nothing
 * about what evidence the question needs.
 */
export function needsEvidenceBeyondTheImage(finding) {
  const method = finding?.detectionMethod;
  return Boolean(method) && !IMAGE_EVALUABLE_METHODS.includes(method);
}

/**
 * The reasons this finding could not be decided, in the backend's own terms.
 *
 * **Nothing here is invented.** Every string returned is either copied from the
 * response or is a fixed sentence describing a flag the response actually set.
 * A UI that made up review reasons - "probably a blurry photo" - would be
 * putting an explanation next to a legal outcome that nothing produced.
 *
 * Returns an empty array for a finding that was decided, so a caller can render
 * the block conditionally without asking about the status twice.
 *
 * @returns {{label: string, detail: string}[]}
 */
export function reviewReasonsFor(finding) {
  if (!finding || finding.status !== 'inconclusive') {
    return [];
  }

  const reasons = [];

  // The applicability resolver names the conditions it could not establish.
  // This is the commonest reason a finding is undetermined and the only one
  // the user can act on, so it comes first.
  const unresolved = finding.details?.unresolved_conditions;
  if (Array.isArray(unresolved) && unresolved.length > 0) {
    reasons.push({
      label: 'A fact deciding whether this rule applies was not stated',
      detail: unresolved.join(', '),
    });
  }

  // Set by the checks that read a normalised value: the extractor would not
  // commit to an interpretation of what it read.
  if (finding.details?.normalisation_uncertain === true) {
    const why = finding.details?.uncertainty_reasons;
    reasons.push({
      label: 'The reading could not be interpreted with confidence',
      detail: Array.isArray(why) ? why.join('; ') : '',
    });
  }

  // The extraction run itself produced nothing usable.
  const extractionStatus = finding.details?.extraction_status;
  if (extractionStatus && extractionStatus !== 'completed') {
    reasons.push({
      label: 'The label could not be read from this photograph',
      detail: `Extraction status: ${extractionStatus}.`,
    });
  }

  if (finding.downgradedFromFailed) {
    reasons.push({
      label: 'The rule behind this check is not verified against the legal text',
      detail:
        'The check did not pass, but an unverified rule can only flag a package for review — it can never report a contravention.',
    });
  }

  if (needsEvidenceBeyondTheImage(finding)) {
    reasons.push({
      label: 'Settling this needs evidence a photograph cannot carry',
      detail: `Detection method: ${finding.detectionMethod}.`,
    });
  }

  return reasons;
}
