import { StatusBadge } from './StatusBadge.jsx';

/**
 * The facts a person asserted about this package.
 *
 * The third kind of evidence on this screen, and the one most easily confused
 * with the other two. Kept in its own card, under its own heading, with its own
 * wording:
 *
 *     Extraction    what the pipeline READ off the photograph
 *     Findings      what the rules CONCLUDED from that
 *     Declarations  what a person SAID about the goods
 *
 * A declaration is not a measurement and must never be drawn as one. It is also
 * not a finding: it is an *input* to applicability, which the engine then
 * applies. So nothing here carries a compliance tone — the badge shows the
 * answer, not a verdict.
 *
 * Empty is the ordinary case and says something useful: nothing was stated, so
 * the clauses that turn on those facts could not be decided either way.
 */
export function DeclarationsPanel({ declarations }) {
  return (
    <div className="card">
      <div className="card__header">
        <h3 className="card__title">What you told us about this package</h3>
        {declarations.length > 0 && (
          <span className="verdict__meta">{declarations.length} stated</span>
        )}
      </div>

      <div className="card__body">
        <p className="hint">
          These were <strong>stated by a person</strong>, not read off the
          photo. Several requirements apply, or do not apply, on facts a camera
          cannot see, and the engine uses these to decide which rules govern
          this package. <strong>Nothing here was verified.</strong>
        </p>
      </div>

      {declarations.length === 0 ? (
        <div className="card__body">
          <div className="empty-state">
            <p>
              No fact was stated about this package. Any clause whose
              applicability turns on one was reported as needing review rather
              than being decided either way.
            </p>
          </div>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="fields-table">
            <thead>
              <tr>
                <th scope="col">Fact</th>
                <th scope="col">Answer</th>
                <th scope="col">Stated by</th>
              </tr>
            </thead>
            <tbody>
              {declarations.map((declaration) => (
                <tr key={declaration.code}>
                  <th scope="row">
                    {declaration.name}
                    {declaration.note && (
                      <span className="is-muted"> — {declaration.note}</span>
                    )}
                  </th>
                  <td>
                    {/*
                      Neutral tone throughout. "Yes" to an exemption is not a
                      good outcome and "no" is not a bad one; colouring these
                      would read as a verdict on an input.
                    */}
                    <StatusBadge
                      value={declaration.answer}
                      tone="neutral"
                      label={declaration.answerDisplay || declaration.answer}
                    />
                  </td>
                  <td className="is-muted">
                    {declaration.sourceDisplay || declaration.source}
                    {/*
                      False, not merely falsy: null means the comparison could
                      not be made, and flagging that as "recorded afterwards"
                      would assert something nobody established.
                    */}
                    {declaration.statedBeforeThisCheck === false && (
                      <>
                        {' '}
                        <span className="is-muted">
                          (recorded after this check ran, so it did not affect
                          this result)
                        </span>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
