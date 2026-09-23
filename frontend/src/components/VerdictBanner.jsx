import { isUnrecognisedResult, toneForResult } from '../utils/compliance.js';
import { formatDateTime, humaniseCode } from '../utils/format.js';

/**
 * The verdict, its explanation, and the counts behind it.
 *
 * The first screenful of a result, and the part most likely to be read on its
 * own — so it has to carry the outcome, the arithmetic behind it and what to do
 * next without anything below it. Five things here are deliberate and should
 * survive a redesign:
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
 * 4. **The right-hand slot carries the engine version, not a score.** No
 *    aggregate exists in the API, and inventing one from per-field confidences
 *    would put a number on the screen that nothing computed. **There is
 *    deliberately no compliance score anywhere in this application.** A
 *    percentage would imply that partial compliance with a labelling
 *    requirement is partial credit, which is not how the Rules work.
 * 5. **Rules that did not apply are counted apart from the passes.** Folding an
 *    exemption into "passed" would turn a set of carve-outs into a clean bill
 *    of health, which is the arithmetic the engine goes out of its way to
 *    avoid.
 *
 * The counts now read as a sentence above the chips as well as inside them.
 * "1 requirement failed, 6 require review" is what a person repeats to a
 * colleague; a row of chips is what they check it against.
 */
export function VerdictBanner({ result }) {
  const tone = toneForResult(result.result);
  const unrecognised = isUnrecognisedResult(result.result);
  const headline = countSentence(result);

  const subject = subjectLine(result);

  return (
    <section
      className={`verdict verdict--${tone} glass`}
      aria-label="Compliance verdict"
    >
      {/*
        The report header: the outcome as a mark and a word, what was
        inspected, and when. It reads top-to-bottom as an inspection record
        rather than as a status field on a form - which is the difference
        between this screen feeling like a report and feeling like a database
        row.
      */}
      <div className="verdict__head">
        <div className="verdict__identity">
          <span
            className={`verdict__mark verdict__mark--${tone}`}
            aria-hidden="true"
          >
            {MARK_BY_TONE[tone] ?? '?'}
          </span>
          <div className="verdict__words">
            <p className="verdict__eyebrow">Automated compliance check</p>
            <h2 className="verdict__title">
              {/*
                The backend's own label, not one restated here, so the two
                cannot drift. Falls back to the raw value for a verdict with
                no label.
              */}
              {result.resultDisplay || result.result || 'Unknown result'}
            </h2>
            {subject && <p className="verdict__subject">{subject}</p>}
          </div>
        </div>
        <p className="verdict__meta">
          Compliance engine v{result.engineVersion}
          {result.processingMs !== null && ` · ${result.processingMs} ms`}
        </p>
      </div>

      {headline && <p className="verdict__headline">{headline}</p>}

      <p className="verdict__summary">{result.summary}</p>

      {/*
        The summary tiles. Every number is one the engine reported; nothing
        here is derived, averaged or turned into a rate. The word beside each
        number is what carries its meaning - the tint is decoration on top of a
        label that already says the same thing.
      */}
      <div className="verdict__counts">
        <Tile tone="success" value={result.rulesPassed} label="passed" />
        <Tile tone="error" value={result.rulesFailed} label="failed" />
        <Tile
          tone="review"
          value={result.rulesInconclusive}
          label={`${result.rulesInconclusive === 1 ? 'requires' : 'require'} review`}
        />
        {/*
          Null against a backend that predates the count, and omitted then
          rather than drawn as zero - "no rule was exempt" and "this server
          does not report exemptions" are different claims.
        */}
        {result.rulesNotApplicable !== null && (
          <Tile
            tone="muted"
            value={result.rulesNotApplicable}
            label="did not apply"
          />
        )}
        {/*
          "examined", not "requirements examined". The longer label was the one
          tile in the row that wrapped to two lines, which left the summary
          looking ragged for no gain - the heading above the row already says
          these are requirements.
        */}
        <Tile value={result.rulesEvaluated} label="examined" />
      </div>

      {result.rulesInconclusive > 0 && (
        <p className="verdict__note">
          <strong>Human review is recommended</strong> for the{' '}
          {result.rulesInconclusive} item(s) marked “requires review” below.
          Each one says why it could not be decided and what would settle it.
        </p>
      )}

      {result.rulesNotApplicable > 0 && (
        <p className="verdict__note verdict__note--muted">
          <strong>Requirements that did not apply are not passes.</strong>{' '}
          {result.rulesNotApplicable} requirement(s) did not govern this
          package, so nothing about those declarations was examined. They are
          excluded from the count of requirements examined for that reason.
        </p>
      )}

      {result.result === 'review_required' && (
        <p className="verdict__note">
          <strong>Requires review. This is not a pass.</strong> The system could
          not responsibly reach a conclusion — because no rules applied, the
          product type was not known, or the photo could not be read — and a
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

/**
 * One summary tile: a count the engine reported, and the word for it.
 *
 * **The count and the word are one text node, and must stay that way.** An
 * earlier draft set the number in its own `<span>` so it could be styled
 * large, which broke two assertions and would have broken more than that:
 * Testing Library's `getNodeText` joins only an element's *direct* text
 * children, so "1" and "failed" in sibling spans are no longer findable as
 * "1 failed" — and a screen reader has the same problem, announcing two
 * fragments where a person reads one phrase.
 *
 * So the tile is a dot and a sentence. The number is not set at 2rem; the
 * tile's own size and border carry the emphasis instead, which is the cheaper
 * half of the effect and costs nothing that matters.
 */
function Tile({ tone, value, label }) {
  return (
    <span className={`count-chip${tone ? ` count-chip--${tone}` : ''}`}>
      <span className="count-chip__dot" aria-hidden="true" />
      {value} {label}
    </span>
  );
}

/**
 * What was inspected and when, or null when the response says neither.
 *
 * Both halves come straight from the response: the product category the rules
 * were selected for, and the moment the evaluation completed. **No product
 * name is shown, because the API does not carry one** - this system reads
 * labels, it does not identify products, and printing a name here would be the
 * one invented fact on the screen.
 */
function subjectLine(result) {
  const parts = [];
  if (result.productCategoryCode) {
    parts.push(humaniseCode(result.productCategoryCode));
  }
  const checkedAt = formatDateTime(result.completedAt);
  if (checkedAt) {
    parts.push(`Checked ${checkedAt}`);
  }
  return parts.length > 0 ? parts.join(' · ') : null;
}

/**
 * A mark per tone, so the outcome is never carried by colour alone.
 *
 * Keyed by tone rather than by verdict, because `toneForResult` is already the
 * one place that maps a backend value to an appearance and a second mapping
 * here could disagree with it. An unrecognised verdict tones to `neutral` and
 * gets the question mark, which is the honest glyph for it.
 */
const MARK_BY_TONE = Object.freeze({
  success: '✓',
  error: '!',
  warning: '!',
  review: '?',
  neutral: '?',
});

/**
 * The counts as one sentence, or null when there is nothing to say.
 *
 * Reports only the non-zero categories and only what the response actually
 * carries. Nothing is computed beyond addition of the engine's own counts: no
 * percentage, no score, no ratio. Returns null when every count is zero, in
 * which case the engine's summary is the only honest thing on screen and it is
 * already shown below.
 */
function countSentence(result) {
  const parts = [];
  if (result.rulesFailed > 0) {
    parts.push(`${result.rulesFailed} ${plural(result.rulesFailed, 'requirement')} failed`);
  }
  if (result.rulesInconclusive > 0) {
    const verb = result.rulesInconclusive === 1 ? 'requires' : 'require';
    parts.push(
      `${result.rulesInconclusive} ${plural(result.rulesInconclusive, 'requirement')} ${verb} review`,
    );
  }
  if (result.rulesPassed > 0) {
    parts.push(`${result.rulesPassed} passed`);
  }
  if (parts.length === 0) {
    return null;
  }
  return `${parts.join(' · ')}.`;
}

function plural(count, word) {
  return count === 1 ? word : `${word}s`;
}
