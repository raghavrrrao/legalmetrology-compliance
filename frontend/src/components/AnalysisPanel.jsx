import { PHASES } from '../hooks/useLabelAnalysis.js';

/**
 * What is happening while a label is being checked.
 *
 * Shown in place of the form for as long as a request is in flight: the
 * photograph the user chose, a scan line travelling over it, and the stages of
 * the pipeline with the one that is actually running marked.
 *
 * **Four stages, not five, and the difference is the point.**
 *
 * A five-step list reading "image received / reading label / extracting
 * declarations / checking requirements / preparing findings" would look better
 * and would be a lie. This client makes exactly two requests:
 *
 *     POST /api/v1/extraction/   recognises the text AND extracts declarations
 *     POST /api/v1/compliance/   evaluates the rules AND assembles findings
 *
 * so "reading" and "extracting" are one server call whose intermediate state
 * the browser cannot observe, and so are "checking" and "preparing". Splitting
 * either into two ticks would be an animation pretending to be telemetry -
 * the progress bar equivalent of a fabricated confidence, and the same kind of
 * dishonesty this project refuses everywhere else.
 *
 * So each stage here corresponds to a state the client genuinely knows it is
 * in, and every stage that has completed reports something real:
 * `declarationsRead` is counted from the response, not estimated.
 *
 * **No percentage, and no timer.** Nothing here counts up, fills a bar, or
 * predicts how long anything will take. The pipeline does not report progress
 * and the client will not invent it. The scan line is decoration over a state
 * that is already stated in words, which is why it is `aria-hidden` and why it
 * stops entirely under `prefers-reduced-motion`.
 */
export function AnalysisPanel({ previewUrl, fileName, phase, declarationsRead }) {
  const stages = stagesFor(phase, declarationsRead);
  const active = stages.find((stage) => stage.state === 'active');

  return (
    <section className="analysis" aria-labelledby="analysis-heading">
      <div className="analysis__stage-wrap">
        <div className="analysis__frame">
          {previewUrl ? (
            <img
              className="analysis__image"
              src={previewUrl}
              alt={
                fileName
                  ? `The label being checked: ${fileName}`
                  : 'The label being checked'
              }
            />
          ) : (
            <div className="analysis__placeholder" aria-hidden="true" />
          )}

          {/*
            The scan line and the corner brackets. Decoration over a state the
            text below already names, so both are hidden from assistive
            technology and both stop under reduced motion.
          */}
          <span className="analysis__scanline" aria-hidden="true" />
          <span className="analysis__brackets" aria-hidden="true" />
        </div>
      </div>

      <div className="analysis__body">
        <p className="analysis__eyebrow">Inspection in progress</p>
        <h2 className="analysis__title" id="analysis-heading">
          {active ? active.label : 'Working…'}
        </h2>
        <p className="analysis__note">
          The photograph is checked on the server. Nothing is decided in this
          browser.
        </p>

        {/*
          `aria-live="polite"` so a screen reader hears each stage as it is
          reached, rather than nothing at all until the result appears.
        */}
        <ol className="analysis__stages" aria-live="polite">
          {stages.map((stage) => (
            <li
              className={`analysis__stage analysis__stage--${stage.state}`}
              key={stage.key}
            >
              <span className="analysis__marker" aria-hidden="true">
                {stage.state === 'done' ? '✓' : ''}
              </span>
              <span className="analysis__stage-text">
                <span className="analysis__stage-label">{stage.label}</span>
                {stage.detail && (
                  <span className="analysis__stage-detail">{stage.detail}</span>
                )}
              </span>
              {/* The state in words, for anyone not seeing the marker. */}
              <span className="visually-hidden">{SPOKEN[stage.state]}</span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

const SPOKEN = Object.freeze({
  done: 'complete',
  active: 'in progress',
  pending: 'not started',
});

/**
 * The stages, and which one each phase puts in progress.
 *
 * `declarationsRead` is attached to the reading stage once it has completed,
 * because by then the client holds the extraction response and can count them.
 * Before that it is null and no detail is shown - an unknown count is not
 * rendered as zero.
 */
function stagesFor(phase, declarationsRead) {
  const extracting = phase === PHASES.EXTRACTING;
  const evaluating = phase === PHASES.EVALUATING;
  const readingDone = !extracting;

  return [
    {
      key: 'uploaded',
      label: 'Photograph uploaded',
      state: 'done',
    },
    {
      key: 'reading',
      label: 'Reading the label',
      detail: readingDone
        ? countDetail(declarationsRead)
        : 'Recognising text and locating declarations',
      state: extracting ? 'active' : 'done',
    },
    {
      key: 'checking',
      label: 'Checking requirements',
      detail: evaluating
        ? 'Evaluating the rules that apply to this package'
        : null,
      state: evaluating ? 'active' : readingDone ? 'pending' : 'pending',
    },
    {
      key: 'findings',
      label: 'Preparing findings',
      state: 'pending',
    },
  ];
}

/** What the reading stage reports once it is done. Never a guess. */
function countDetail(declarationsRead) {
  if (typeof declarationsRead !== 'number') {
    return null;
  }
  return declarationsRead === 1
    ? '1 declaration read'
    : `${declarationsRead} declarations read`;
}
