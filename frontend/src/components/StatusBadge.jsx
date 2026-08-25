import { humaniseCode } from '../utils/format.js';

/**
 * A small coloured label for a status value.
 *
 * `tone` is chosen by the caller rather than derived from `value` here, so a
 * compliance result and a dependency status can share the component without
 * this file having to know about either vocabulary.
 */
export function StatusBadge({ value, tone = 'neutral' }) {
  return (
    <span className={`status-badge status-badge--${tone}`}>
      {humaniseCode(value)}
    </span>
  );
}
