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

/** Finding outcomes this build knows how to present. */
export const KNOWN_FINDING_STATUSES = Object.freeze([
  'passed',
  'failed',
  'inconclusive',
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
});

/** @returns {'success'|'warning'|'error'|'review'|'neutral'} */
export function toneForResult(result) {
  return TONE_BY_RESULT[result] ?? 'neutral';
}

/** @returns {'success'|'error'|'review'|'neutral'} */
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
