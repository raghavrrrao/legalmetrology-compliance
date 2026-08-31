import { FindingCard } from './FindingCard.jsx';
import { sortFindingsForDisplay } from '../utils/compliance.js';

/**
 * "Key Findings": every rule that was examined, and what it concluded.
 *
 * This is the list `findings[]` fills, and it is not the violations list.
 * `violations` answers "what is wrong with this package?"; this answers "what
 * was actually checked, and on what evidence?" - which a user needs before they
 * can trust the first answer.
 *
 * Three empty states, and they say different things on purpose:
 *
 * - **`findings` absent from the response.** The server predates the field.
 *   Violations still render, so the screen keeps working; this section says the
 *   per-rule trace is unavailable rather than showing an empty list, which
 *   would read as "nothing was checked".
 * - **`findings` empty.** No rule was applicable or none is loaded. That is not
 *   a finding of compliance and the copy says so.
 * - **Findings present.** Ordered failures first, then undetermined, then
 *   passes - so what needs acting on is what is read first.
 */
export function FindingsList({ findings, findingsReported }) {
  if (!findingsReported) {
    return (
      <div className="empty-state">
        <p>
          This backend version does not report per-rule findings, so the list of
          rules that were examined is unavailable. Any violations it did report
          are shown below.
        </p>
      </div>
    );
  }

  if (findings.length === 0) {
    return (
      <div className="empty-state">
        <p>
          No rule was examined against this reading. That is not a finding of
          compliance — it means no applicable rule was loaded, or the commodity
          category was not known. The verdict above explains which.
        </p>
      </div>
    );
  }

  const ordered = sortFindingsForDisplay(findings);

  return (
    <div className="findings">
      {ordered.map((finding, index) => (
        <FindingCard key={finding.id} finding={finding} index={index} />
      ))}
    </div>
  );
}
