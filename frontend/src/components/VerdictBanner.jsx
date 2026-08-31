import {
  isUnrecognisedResult,
  toneForResult,
} from '../utils/compliance.js';

/**
 * The verdict, its explanation, and the counts behind it.
 *
 * The Figma header banner. Four things on it are deliberate and should survive
 * a redesign:
 *
 * 1. **The summary always appears with the verdict.** The engine's explanation
 *    is what distinguishes "we checked and it passed" from "no rules are
 *    loaded, so nothing was checked". A verdict shown alone implies a
 *    determination the system did not make.
 * 2. **REVIEW_REQUIRED gets its own tone and its own sentence.** It is never
 *    drawn as a pass or as a failure.
 * 3. **An unrecognised verdict is called unrecognised.** If the API grows a
 *    fifth value, this renders neutrally and says a person must read the
 *    summary - it does not fall back to a colour that would flatter the result.
 * 4. **The right-hand slot carries the engine version, not a score.** The Figma
 *    shows "Scan Confidence: 94%" there; no such aggregate exists in the API,
 *    and inventing one from per-field confidences would put a number on the
 *    screen that nothing computed.
 */
export function VerdictBanner({ result }) {
  const tone = toneForResult(result.result);
  const unrecognised = isUnrecognisedResult(result.result);

  return (
    <section
      className={`verdict verdict--${tone}`}
      aria-label="Compliance verdict"
    >
      <div className="verdict__head">
        <h2 className="verdict__title">
          <span aria-hidden="true">{tone === 'success' ? '✓' : '⚠'}</span>
          {/*
            The backend's own label, not one restated here, so the two cannot
            drift. Falls back to the raw value for a verdict with no label.
          */}
          {result.resultDisplay || result.result || 'Unknown result'}
        </h2>
        <p className="verdict__meta">
          Compliance engine v{result.engineVersion}
          {result.processingMs !== null && ` · ${result.processingMs} ms`}
        </p>
      </div>

      <p className="verdict__summary">{result.summary}</p>

      <div className="verdict__counts">
        <span className="count-chip count-chip--success">
          <span className="count-chip__dot" aria-hidden="true" />
          {result.rulesPassed} passed
        </span>
        <span className="count-chip count-chip--error">
          <span className="count-chip__dot" aria-hidden="true" />
          {result.rulesFailed} failed
        </span>
        <span className="count-chip count-chip--review">
          <span className="count-chip__dot" aria-hidden="true" />
          {result.rulesInconclusive} undetermined
        </span>
        <span className="count-chip">
          <span className="count-chip__dot" aria-hidden="true" />
          {result.rulesEvaluated} rules examined
        </span>
      </div>

      {result.result === 'review_required' && (
        <p className="verdict__note">
          <strong>Requires review. This is not a pass.</strong> The system could
          not responsibly reach a conclusion — because no rules applied, the
          commodity was not known, or the photograph could not be read — and a
          person needs to look at this label.
        </p>
      )}

      {unrecognised && (
        <p className="verdict__note">
          <strong>This result is not one this build recognises.</strong> It has
          not been interpreted as compliant or non-compliant. Read the
          explanation above and treat the label as needing review.
        </p>
      )}
    </section>
  );
}
