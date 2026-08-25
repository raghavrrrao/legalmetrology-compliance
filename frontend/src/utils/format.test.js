import { describe, expect, it } from 'vitest';

import { formatFileSize, humaniseCode } from './format.js';

describe('formatFileSize', () => {
  it.each([
    [0, '0 B'],
    [512, '512 B'],
    [1024, '1 KB'],
    [1536, '1.5 KB'],
    [1048576, '1 MB'],
    [10485760, '10 MB'],
  ])('formats %i bytes as %s', (bytes, expected) => {
    expect(formatFileSize(bytes)).toBe(expected);
  });

  it.each([[-1], [NaN], ['nope'], [null], [undefined]])(
    'returns "unknown" for %p',
    (value) => {
      expect(formatFileSize(value)).toBe('unknown');
    },
  );
});

describe('humaniseCode', () => {
  it.each([
    ['review_required', 'Review required'],
    ['non_compliant', 'Non compliant'],
    ['net-quantity', 'Net quantity'],
    ['ok', 'Ok'],
  ])('turns %s into %s', (value, expected) => {
    expect(humaniseCode(value)).toBe(expected);
  });

  it('returns an empty string for empty input', () => {
    expect(humaniseCode('')).toBe('');
    expect(humaniseCode(null)).toBe('');
  });
});
