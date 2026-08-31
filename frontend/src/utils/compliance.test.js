/**
 * The presentation helpers.
 *
 * The important assertions here are the negative ones. An unknown status must
 * not inherit a tone that flatters it, and a bounding box that is not four
 * usable numbers must produce no rectangle rather than a plausible one.
 */

import { describe, expect, it } from 'vitest';

import {
  boundingBoxToPercentages,
  formatConfidence,
  isUnrecognisedFindingStatus,
  isUnrecognisedResult,
  sortFindingsForDisplay,
  toneForFindingStatus,
  toneForResult,
} from './compliance.js';

describe('toneForResult', () => {
  it('gives review_required its own tone, not a pass or a failure', () => {
    expect(toneForResult('review_required')).toBe('review');
    expect(toneForResult('compliant')).toBe('success');
    expect(toneForResult('non_compliant')).toBe('error');
    expect(toneForResult('partially_compliant')).toBe('warning');
  });

  it('falls back to neutral for a verdict it has never seen', () => {
    expect(toneForResult('something_new')).toBe('neutral');
    expect(toneForResult(undefined)).toBe('neutral');
    expect(isUnrecognisedResult('something_new')).toBe(true);
    expect(isUnrecognisedResult('compliant')).toBe(false);
  });
});

describe('toneForFindingStatus', () => {
  it('keeps inconclusive distinct from both pass and fail', () => {
    expect(toneForFindingStatus('passed')).toBe('success');
    expect(toneForFindingStatus('failed')).toBe('error');
    expect(toneForFindingStatus('inconclusive')).toBe('review');
  });

  it('never renders an unknown status as a pass', () => {
    expect(toneForFindingStatus('deferred')).toBe('neutral');
    expect(isUnrecognisedFindingStatus('deferred')).toBe(true);
    expect(isUnrecognisedFindingStatus('inconclusive')).toBe(false);
  });
});

describe('sortFindingsForDisplay', () => {
  it('puts failures first, then undecided, then passes', () => {
    const sorted = sortFindingsForDisplay([
      { id: 1, status: 'passed' },
      { id: 2, status: 'inconclusive' },
      { id: 3, status: 'failed' },
    ]);

    expect(sorted.map((f) => f.id)).toEqual([3, 2, 1]);
  });

  it('surfaces an unknown status rather than burying it', () => {
    const sorted = sortFindingsForDisplay([
      { id: 1, status: 'passed' },
      { id: 2, status: 'mystery' },
    ]);

    expect(sorted[0].id).toBe(2);
  });

  it('does not mutate its input', () => {
    const input = [{ id: 1, status: 'passed' }, { id: 2, status: 'failed' }];
    sortFindingsForDisplay(input);
    expect(input.map((f) => f.id)).toEqual([1, 2]);
  });
});

describe('formatConfidence', () => {
  it('renders a fraction as a percentage', () => {
    expect(formatConfidence(0.91)).toBe('91%');
    expect(formatConfidence(0)).toBe('0%');
  });

  it('returns null for an unreported confidence, never "0%"', () => {
    expect(formatConfidence(null)).toBeNull();
    expect(formatConfidence(undefined)).toBeNull();
    expect(formatConfidence(Number.NaN)).toBeNull();
  });
});

describe('boundingBoxToPercentages', () => {
  it('expresses a box as percentages of the source image', () => {
    expect(
      boundingBoxToPercentages({ x: 40, y: 60, width: 200, height: 30 }, 800, 600),
    ).toEqual({ left: '5%', top: '10%', width: '25%', height: '5%' });
  });

  it('refuses to guess at a box it cannot use', () => {
    expect(boundingBoxToPercentages(null, 800, 600)).toBeNull();
    expect(boundingBoxToPercentages({ x: 1, y: 1 }, 800, 600)).toBeNull();
    expect(
      boundingBoxToPercentages({ x: 1, y: 1, width: 0, height: 5 }, 800, 600),
    ).toBeNull();
    expect(
      boundingBoxToPercentages({ x: 1, y: 1, width: 5, height: 5 }, 0, 600),
    ).toBeNull();
    expect(
      boundingBoxToPercentages({ x: 1, y: 1, width: 5, height: 5 }, undefined, 600),
    ).toBeNull();
  });
});
