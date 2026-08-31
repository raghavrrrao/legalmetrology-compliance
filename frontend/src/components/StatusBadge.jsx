import { humaniseCode } from '../utils/format.js';

/**
 * A small coloured label for a status value.
 *
 * `tone` is chosen by the caller rather than derived from `value` here, so a
 * compliance result, a finding status and a dependency status can share the
 * component without this file having to know about any of those vocabularies.
 *
 * `label` overrides the displayed text for the cases where the API's word is
 * not the user's - the raw value is still what the caller branched on.
 */
export function StatusBadge({ value, tone = 'neutral', label }) {
  return (
    <span className={`status-badge status-badge--${tone}`}>
      {label ?? humaniseCode(value)}
    </span>
  );
}
