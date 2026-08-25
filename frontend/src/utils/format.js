/** Small formatting helpers shared across components. */

/** Bytes as a human-readable size, e.g. 2048 -> "2 KB". */
export function formatFileSize(bytes) {
  if (typeof bytes !== 'number' || Number.isNaN(bytes) || bytes < 0) {
    return 'unknown';
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const rounded = value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${units[unitIndex]}`;
}

/**
 * Turn a snake_case API value into a readable label, e.g.
 * "review_required" -> "Review required".
 *
 * For display only. Never derive logic from the result - branch on the raw
 * value, which is the stable contract.
 */
export function humaniseCode(value) {
  if (!value) {
    return '';
  }
  const spaced = String(value).replace(/[_-]+/g, ' ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
