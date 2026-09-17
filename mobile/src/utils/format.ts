/**
 * Small formatting helpers. Presentation only: nothing here interprets a
 * value, only spells it.
 */

/** `net_quantity` -> "Net quantity"; `packaged-food` -> "Packaged food". */
export function humaniseCode(value: string | null | undefined): string {
  if (!value) {
    return '';
  }
  const spaced = value.replace(/[_-]+/g, ' ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * A confidence in [0, 1] as a whole-number percentage, or "Not reported" for
 * null. Null is never rendered as 0%: the engine not saying is not the engine
 * saying zero.
 */
export function formatConfidence(value: number | null | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return 'Not reported';
  }
  const clamped = Math.max(0, Math.min(1, value));
  return `${Math.round(clamped * 100)}%`;
}

/** Bytes as "1.2 MB" / "340 KB", or "" for null. */
export function formatBytes(bytes: number | null | undefined): string {
  if (typeof bytes !== 'number' || bytes < 0) {
    return '';
  }
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${bytes} B`;
}

/** Milliseconds as "2.2 s", or "" for null. */
export function formatDuration(ms: number | null | undefined): string {
  if (typeof ms !== 'number' || ms < 0) {
    return '';
  }
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

/**
 * A normalised value as a short string. The value is whatever the backend's
 * normaliser produced - `{quantity: 500, unit: "g"}`, `{amount: 149,
 * currency: "INR"}` - and its keys are not known here, so it is rendered as
 * "key: value" pairs rather than interpreted.
 */
export function formatNormalizedValue(value: Record<string, unknown> | null | undefined): string {
  if (!value || typeof value !== 'object') {
    return '';
  }
  return Object.entries(value)
    .filter(([, item]) => item !== null && item !== undefined && item !== '')
    .map(([key, item]) => `${humaniseCode(key)}: ${typeof item === 'object' ? JSON.stringify(item) : String(item)}`)
    .join(' · ');
}
