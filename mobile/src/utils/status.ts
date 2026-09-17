/**
 * Presentation lookups for statuses the backend already decided.
 *
 * **This file makes no compliance decision and must never be allowed to.**
 * It answers "what colour and what icon is this status?" and "what order do
 * findings appear in?" from a value the backend returned. Nothing derives a
 * verdict, combines statuses, thresholds a confidence, or infers an outcome
 * the response did not state. Mirrors `frontend/src/utils/compliance.js`.
 *
 * The lookups are deliberately partial and every caller falls back to
 * `neutral`. A status this build has never heard of - a value added to the
 * API after this build shipped - must render as unrecognised, not inherit the
 * appearance of whichever entry happened to be the default. Rendering an
 * unknown status in green is the specific failure this shape prevents.
 *
 * Every tone carries a symbol as well as a colour, so status is never
 * conveyed by colour alone.
 */

export type Tone = 'success' | 'warning' | 'error' | 'review' | 'muted' | 'neutral';

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
  'not_applicable',
]);

const TONE_BY_RESULT: Readonly<Record<string, Tone>> = Object.freeze({
  compliant: 'success',
  partially_compliant: 'warning',
  non_compliant: 'error',
  // Not 'success' and not 'error'. It means a person needs to look at this.
  review_required: 'review',
});

const TONE_BY_FINDING_STATUS: Readonly<Record<string, Tone>> = Object.freeze({
  passed: 'success',
  failed: 'error',
  inconclusive: 'review',
  // Not 'success'. Nothing was checked, so there is nothing to be green about.
  not_applicable: 'muted',
});

/** A text symbol per tone, read out by screen readers alongside the label. */
export const SYMBOL_BY_TONE: Readonly<Record<Tone, string>> = Object.freeze({
  success: '✓',
  warning: '!',
  error: '✕',
  review: '?',
  muted: '–',
  neutral: '•',
});

export function toneForResult(result: string | null | undefined): Tone {
  return (result && TONE_BY_RESULT[result]) || 'neutral';
}

export function toneForFindingStatus(status: string | null | undefined): Tone {
  return (status && TONE_BY_FINDING_STATUS[status]) || 'neutral';
}

/**
 * The label for a finding status, in the user's words rather than the API's.
 * Anything unrecognised is humanised from the raw value so it still reads.
 */
export function findingStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case 'passed':
      return 'Passed';
    case 'failed':
      return 'Failed';
    case 'inconclusive':
      return 'Needs review';
    case 'not_applicable':
      return 'Not applicable';
    default:
      return status ? status.replace(/[_-]+/g, ' ') : 'Unknown';
  }
}

/**
 * The order finding groups appear on the result screen: what a reviewer has
 * to act on first, exemptions last.
 */
export const FINDING_STATUS_ORDER: readonly string[] = Object.freeze([
  'failed',
  'inconclusive',
  'passed',
  'not_applicable',
]);

/** Group findings by status, in display order, unknown statuses last. */
export function groupFindingsByStatus<T extends { status: string }>(findings: T[]): { status: string; items: T[] }[] {
  const groups = new Map<string, T[]>();
  for (const finding of findings) {
    const key = finding.status || 'unknown';
    const bucket = groups.get(key);
    if (bucket) {
      bucket.push(finding);
    } else {
      groups.set(key, [finding]);
    }
  }
  const ordered: { status: string; items: T[] }[] = [];
  for (const status of FINDING_STATUS_ORDER) {
    const items = groups.get(status);
    if (items) {
      ordered.push({ status, items });
      groups.delete(status);
    }
  }
  for (const [status, items] of groups) {
    ordered.push({ status, items });
  }
  return ordered;
}
