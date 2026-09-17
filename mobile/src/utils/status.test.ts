/**
 * Presentation lookups. The one property that matters: an unrecognised
 * status never inherits the look of a recognised one.
 */

import {
  findingStatusLabel,
  groupFindingsByStatus,
  toneForFindingStatus,
  toneForResult,
} from './status';
import { formatConfidence, formatNormalizedValue, humaniseCode } from './format';

describe('toneForResult', () => {
  it('maps each verdict the backend defines', () => {
    expect(toneForResult('compliant')).toBe('success');
    expect(toneForResult('partially_compliant')).toBe('warning');
    expect(toneForResult('non_compliant')).toBe('error');
    expect(toneForResult('review_required')).toBe('review');
  });

  it('renders an unknown verdict as neutral, never green', () => {
    expect(toneForResult('something_new')).toBe('neutral');
    expect(toneForResult('')).toBe('neutral');
    expect(toneForResult(null)).toBe('neutral');
  });
});

describe('toneForFindingStatus', () => {
  it('keeps inconclusive and not_applicable away from success', () => {
    expect(toneForFindingStatus('passed')).toBe('success');
    expect(toneForFindingStatus('failed')).toBe('error');
    expect(toneForFindingStatus('inconclusive')).toBe('review');
    expect(toneForFindingStatus('not_applicable')).toBe('muted');
    expect(toneForFindingStatus('mystery')).toBe('neutral');
  });
});

describe('findingStatusLabel', () => {
  it('uses plain words and humanises anything unknown', () => {
    expect(findingStatusLabel('inconclusive')).toBe('Needs review');
    expect(findingStatusLabel('not_applicable')).toBe('Not applicable');
    expect(findingStatusLabel('brand_new')).toBe('brand new');
    expect(findingStatusLabel(undefined)).toBe('Unknown');
  });
});

describe('groupFindingsByStatus', () => {
  it('orders failures first, exemptions last, unknown statuses after', () => {
    const groups = groupFindingsByStatus([
      { id: 1, status: 'not_applicable' },
      { id: 2, status: 'passed' },
      { id: 3, status: 'failed' },
      { id: 4, status: 'inconclusive' },
      { id: 5, status: 'weird' },
      { id: 6, status: 'failed' },
    ]);

    expect(groups.map((group) => group.status)).toEqual(['failed', 'inconclusive', 'passed', 'not_applicable', 'weird']);
    expect(groups[0].items.map((item) => item.id)).toEqual([3, 6]);
  });

  it('returns nothing for nothing', () => {
    expect(groupFindingsByStatus([])).toEqual([]);
  });
});

describe('format helpers', () => {
  it('humanises codes', () => {
    expect(humaniseCode('net_quantity')).toBe('Net quantity');
    expect(humaniseCode('packaged-food')).toBe('Packaged food');
    expect(humaniseCode('')).toBe('');
  });

  it('formats a confidence as a percentage and null as not reported', () => {
    expect(formatConfidence(0.7232)).toBe('72%');
    expect(formatConfidence(1)).toBe('100%');
    expect(formatConfidence(null)).toBe('Not reported');
    expect(formatConfidence(undefined)).toBe('Not reported');
  });

  it('spells a normalised value without interpreting it', () => {
    expect(formatNormalizedValue({ quantity: 500, unit: 'g', uncertain: false })).toBe(
      'Quantity: 500 · Unit: g · Uncertain: false',
    );
    expect(formatNormalizedValue(null)).toBe('');
  });
});
