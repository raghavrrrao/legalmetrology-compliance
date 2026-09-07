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
  needsEvidenceBeyondTheImage,
  reviewReasonsFor,
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

describe('not_applicable', () => {
  it('is a status this build knows, and is not a pass', () => {
    expect(isUnrecognisedFindingStatus('not_applicable')).toBe(false);
    expect(toneForFindingStatus('not_applicable')).toBe('muted');
    expect(toneForFindingStatus('not_applicable')).not.toBe('success');
  });

  it('sorts after the passes, because nothing about it was examined', () => {
    const ordered = sortFindingsForDisplay([
      { id: 1, status: 'not_applicable' },
      { id: 2, status: 'passed' },
      { id: 3, status: 'failed' },
      { id: 4, status: 'inconclusive' },
    ]);

    expect(ordered.map((finding) => finding.id)).toEqual([3, 4, 2, 1]);
  });
});

describe('needsEvidenceBeyondTheImage', () => {
  it('is true for evidence a photograph cannot carry', () => {
    expect(
      needsEvidenceBeyondTheImage({ detectionMethod: 'physical_inspection' }),
    ).toBe(true);
    expect(needsEvidenceBeyondTheImage({ detectionMethod: 'database' })).toBe(true);
  });

  it('is false for the methods this pipeline actually has', () => {
    expect(needsEvidenceBeyondTheImage({ detectionMethod: 'ocr' })).toBe(false);
    expect(needsEvidenceBeyondTheImage({ detectionMethod: 'ocr_cv' })).toBe(false);
    expect(needsEvidenceBeyondTheImage({ detectionMethod: 'cv' })).toBe(false);
  });

  it('does not treat an unmapped rule as needing a physical inspection', () => {
    // The field is blank when the rule is not linked to the legal framework,
    // which says nothing about what evidence the question would need.
    expect(needsEvidenceBeyondTheImage({ detectionMethod: '' })).toBe(false);
    expect(needsEvidenceBeyondTheImage({})).toBe(false);
    expect(needsEvidenceBeyondTheImage(null)).toBe(false);
  });
});

describe('reviewReasonsFor', () => {
  it('says nothing about a finding that was decided', () => {
    expect(reviewReasonsFor({ status: 'passed', details: {} })).toEqual([]);
    expect(reviewReasonsFor({ status: 'failed', details: {} })).toEqual([]);
    expect(reviewReasonsFor({ status: 'not_applicable', details: {} })).toEqual([]);
  });

  it('names the facts the engine could not establish', () => {
    const reasons = reviewReasonsFor({
      status: 'inconclusive',
      details: { unresolved_conditions: ['bidi', 'domestic-lpg-cylinder'] },
    });

    expect(reasons).toHaveLength(1);
    expect(reasons[0].detail).toContain('bidi');
  });

  it('reports an unreadable photograph and an uninterpretable reading apart', () => {
    const unreadable = reviewReasonsFor({
      status: 'inconclusive',
      details: { extraction_status: 'empty' },
    });
    const uninterpretable = reviewReasonsFor({
      status: 'inconclusive',
      details: {
        normalisation_uncertain: true,
        uncertainty_reasons: ['both DD/MM and MM/DD are valid readings'],
      },
    });

    expect(unreadable[0].label).toMatch(/could not be read/i);
    expect(uninterpretable[0].label).toMatch(/could not be interpreted/i);
    expect(uninterpretable[0].detail).toContain('DD/MM');
  });

  it('invents nothing when the response gives no reason', () => {
    // An undetermined finding with no diagnostics is a real state, and a
    // plausible-sounding guess next to a legal outcome is worse than silence.
    expect(reviewReasonsFor({ status: 'inconclusive', details: {} })).toEqual([]);
    expect(reviewReasonsFor({ status: 'inconclusive' })).toEqual([]);
  });

  it('reports the unverified-rule safeguard when it fired', () => {
    const reasons = reviewReasonsFor({
      status: 'inconclusive',
      downgradedFromFailed: true,
      details: {},
    });

    expect(reasons[0].label).toMatch(/not verified/i);
  });
});
