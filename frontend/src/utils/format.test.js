import { describe, expect, it } from 'vitest';

import { formatDateTime, formatFileSize, humaniseCode } from './format.js';

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

describe('formatDateTime', () => {
  it('renders an ISO timestamp as a readable local date and time', () => {
    const rendered = formatDateTime('2026-08-30T12:00:00Z');

    // The exact wording is the reader's locale's business; that the timestamp
    // was understood at all is this file's.
    expect(rendered).toMatch(/2026/);
    expect(rendered).not.toMatch(/invalid/i);
  });

  it('returns null for a missing or unparseable value', () => {
    expect(formatDateTime(null)).toBeNull();
    expect(formatDateTime('')).toBeNull();
    expect(formatDateTime('not-a-date')).toBeNull();
    expect(formatDateTime(undefined)).toBeNull();
  });
});
