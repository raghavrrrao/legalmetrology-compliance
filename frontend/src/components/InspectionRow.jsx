import { Link } from 'react-router-dom';

import { StatusBadge } from './StatusBadge.jsx';
import { isUnrecognisedResult, toneForResult } from '../utils/compliance.js';
import { formatDateTime, humaniseCode } from '../utils/format.js';

/**
 * One stored compliance check, as a row of the Inspections list.
 *
 * A card rather than a table row, and the same card at every width: history is
 * six short facts and a link, which stack on a phone and sit on one line on a
 * desktop without a second markup tree to keep in step. Nothing scrolls
 * sideways as a result.
 *
 * Three things here are deliberate:
 *
 * 1. **The link is a link.** The card is not clickable; the result id is, as a
 *    `Link` to `/result/<id>`. That is what makes the row reachable by keyboard
 *    and openable in a new tab, and it is why there is no `onClick` on the
 *    article and no `role="button"` anywhere on it.
 * 2. **`status` and `result` are not collapsed.** They answer different
 *    questions - whether the evaluation ran, and what it concluded - and the
 *    backend keeps them apart. A check that did not complete shows its
 *    lifecycle and says why no verdict is shown, rather than displaying the
 *    model's default verdict as though something had concluded it.
 * 3. **No status is conveyed by colour alone.** Every badge and chip carries
 *    its own words; the tone is decoration on top of a label that already says
 *    the same thing.
 *
 * This row shows what the *list* endpoint returns and nothing more. The
 * findings, the violations and the reading are on the result screen, which is
 * where the link goes.
 */
export function InspectionRow({ row }) {
  const id = row.id ? String(row.id) : '';
  const isCompleted = row.status === 'completed';
  const checkedAt = formatDateTime(row.createdAt);

  return (
    <article className="history-item">
      <div className="history-item__head">
        <h3 className="history-item__title">
          {id ? (
            <Link to={`/result/${id}`}>Result {id.slice(0, 8)}</Link>
          ) : (
            // A row the API sent without an id cannot be opened. Saying so is
            // the honest answer; a link to `/result/undefined` is not.
            <span>Result (no identifier returned)</span>
          )}
        </h3>

        {isCompleted ? (
          <StatusBadge
            value={row.result}
            tone={toneForResult(row.result)}
            // The backend's own label where it sent one, so the two cannot
            // drift; the raw value humanised where it did not.
            label={row.resultDisplay || undefined}
          />
        ) : (
          <StatusBadge
            value={row.status}
            tone="neutral"
            label={row.status ? undefined : 'State not reported'}
          />
        )}
      </div>

      <dl className="history-item__meta">
        <div>
          <dt>Checked</dt>
          <dd>
            {checkedAt ? (
              <time dateTime={row.createdAt}>{checkedAt}</time>
            ) : (
              'Not recorded'
            )}
          </dd>
        </div>
        <div>
          <dt>Commodity category</dt>
          <dd>{row.productCategoryCode || 'Not known'}</dd>
        </div>
        <div>
          <dt>Engine</dt>
          <dd>{row.engineVersion ? `v${row.engineVersion}` : 'Not reported'}</dd>
        </div>
      </dl>

      <div className="history-item__counts">
        {/*
          Null, never zero. A backend that did not report a count has not said
          that no rule was examined, and a chip reading "0 rules examined" would
          say exactly that.
        */}
        {row.findingsCount !== null && (
          <span className="count-chip">
            <span className="count-chip__dot" aria-hidden="true" />
            {pluralise(row.findingsCount, 'rule')} examined
          </span>
        )}
        {row.violationsCount !== null && (
          <span
            className={`count-chip${row.violationsCount > 0 ? ' count-chip--error' : ''}`}
          >
            <span className="count-chip__dot" aria-hidden="true" />
            {pluralise(row.violationsCount, 'violation')}
          </span>
        )}
      </div>

      {!isCompleted && (
        <p className="history-item__note">
          {row.status
            ? `This evaluation is ${humaniseCode(row.status).toLowerCase()}, so no verdict is shown for it.`
            : 'This evaluation reported no state, so no verdict is shown for it.'}
        </p>
      )}

      {isCompleted && isUnrecognisedResult(row.result) && (
        <p className="history-item__note">
          This verdict is not one this build recognises. It has not been
          interpreted as compliant or non-compliant — open the result and read
          its explanation.
        </p>
      )}
    </article>
  );
}

/** "1 rule" / "2 rules". Display only. */
function pluralise(count, noun) {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}
