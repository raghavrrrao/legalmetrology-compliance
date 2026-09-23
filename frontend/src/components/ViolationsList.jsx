import { StatusBadge } from './StatusBadge.jsx';
import { humaniseCode } from '../utils/format.js';
import { imageLabel } from '../utils/images.js';

/**
 * The rules this package was found to fail, with the evidence behind each.
 *
 * `violations[]` is the legal finding of record and predates `findings[]`. It
 * is kept as its own section rather than folded into the findings list: a
 * violation snapshots the rule and carries several evidence rows, and a reader
 * asking "what is wrong with this package?" should get that answer without
 * filtering a longer list themselves. `FindingCard` names the violation a
 * failure became, so the two are navigable in both directions.
 *
 * When an inspection carries several photographs, each evidence row names the
 * one it came from. Only where the backend attributed it: `image_id` is what is
 * rendered, and a row without one says nothing about images rather than
 * defaulting to the first. For a finding of absence the backend falls back to
 * the primary photograph, which is not a claim that the declaration should have
 * been on that panel - so the label is suppressed there too, by
 * `imagePositions` being given fewer than two photographs or by the id simply
 * not resolving.
 *
 * An empty list is not a clean bill of health, and the copy says so without
 * guessing at why it is empty. It used to say "with no verified rules loaded
 * this is expected", which was written when this was the only list on the
 * screen - once rules were actually loaded and passed, that sentence asserted
 * something false. The verdict states what was concluded and the findings list
 * shows what was examined; this section says only what it knows.
 */
export function ViolationsList({ violations, imagePositions }) {
  if (violations.length === 0) {
    return (
      <div className="empty-state">
        <p>
          No rule was recorded as broken. On its own that is not a finding of
          compliance — the verdict above says what was actually concluded, and
          the findings list shows which rules were examined to reach it.
        </p>
      </div>
    );
  }

  return (
    <div className="findings">
      {violations.map((violation) => (
        <article className="finding finding--error" key={violation.id}>
          <div className="finding__head">
            <div className="finding__heading">
              <h4 className="finding__title">{violation.ruleCode}</h4>
              {violation.fieldKey && (
                <p className="finding__rule">
                  {humaniseCode(violation.fieldKey)}
                </p>
              )}
            </div>
            {/*
              Severity is a triage ranking copied from the rule and carries no
              legal weight. Drawn in the warning tone rather than the error tone
              so it cannot be mistaken for the outcome itself.
            */}
            <StatusBadge value={violation.severity} tone="warning" />
          </div>

          <div className="finding__body">
            <p className="finding__message">{violation.message}</p>

            {violation.legalReference && (
              <dl className="detail-list">
                <dt>Regulation</dt>
                <dd className="is-muted">{violation.legalReference}</dd>
              </dl>
            )}

            {violation.evidence.length === 0 ? (
              <p className="hint">No evidence excerpt was recorded.</p>
            ) : (
              violation.evidence.map((item, index) => {
                const source = imageLabel(item.imageId, imagePositions);
                return (
                  <div key={index}>
                    {source && (
                      <p className="evidence__source">{`Evidence · ${source}`}</p>
                    )}
                    {item.excerpt ? (
                      <blockquote className="evidence">{item.excerpt}</blockquote>
                    ) : (
                      <p className="hint">
                        Evidence recorded without a text excerpt.
                      </p>
                    )}
                    {item.note && <p className="hint">{item.note}</p>}
                  </div>
                );
              })
            )}
          </div>
        </article>
      ))}
    </div>
  );
}
