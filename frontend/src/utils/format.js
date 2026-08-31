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

/**
 * An ISO 8601 timestamp as a readable local date and time, or null.
 *
 * Null in, null out - and for anything that is not a parseable date too, so a
 * malformed or absent `created_at` renders as an em dash rather than as
 * "Invalid Date". The caller pairs the result with a `<time dateTime>` holding
 * the raw value, which is the machine-readable one.
 *
 * Formatted in the reader's own locale and timezone. The API sends UTC; a
 * reviewer works in local time, and converting is presentation, not data.
 */
export function formatDateTime(value) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}
