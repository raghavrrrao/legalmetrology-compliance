import { PHASES } from '../hooks/useLabelAnalysis.js';

/**
 * Where the user is in the workflow, and what is happening right now.
 *
 * Four steps, matching the four things the page asks of somebody:
 *
 *     Upload  ->  Package details  ->  Check  ->  Results
 *
 * **It reports state; it does not gate it.** Nothing here hides a section or
 * refuses a click. The page is one screen with everything reachable at once,
 * and this strip exists so a first-time visitor can tell at a glance what they
 * have done and what is left — not to turn that screen into a wizard with
 * three pages of Next.
 *
 * The steps are driven by real state: a step is complete when the thing it
 * describes actually exists (a file chosen, a request in flight, a stored
 * result), never by a timer or a step counter the page increments on its own.
 * "Package details" is marked complete once either a product type or an
 * applicability answer has been given, because both are genuinely optional and
 * marking an optional step "incomplete" forever would misreport a finished
 * check as unfinished.
 *
 * While a request is in flight it also carries one live sentence — "Reading the
 * label…", "Checking requirements…" — because the difference between a slow
 * reader and a slow rule engine is the first thing anyone asks when a
 * demonstration pauses. The strip keeps the analysis-progress label it has
 * always had, so assistive technology announces the same region as before.
 */
const STEPS = [
  { key: 'upload', label: 'Upload' },
  { key: 'details', label: 'Package details' },
  { key: 'check', label: 'Check' },
  { key: 'results', label: 'Results' },
];

/** The sentence shown while a request is actually in flight. */
const RUNNING_LABEL = {
  [PHASES.EXTRACTING]: 'Uploading the photo and reading the label…',
  [PHASES.EVALUATING]: 'Checking the requirements…',
};

export function WorkflowProgress({ phase, hasFile, hasDetails, hasResult }) {
  const running = RUNNING_LABEL[phase] ?? null;
  const busy = running !== null;

  // Index of the step currently in progress, or -1 when nothing is running.
  const active = busy ? 2 : -1;

  const done = [
    hasFile,
    hasDetails,
    hasResult,
    hasResult && phase === PHASES.COMPLETE,
  ];

  return (
    <div className="workflow" aria-label="Analysis progress">
      <ol className="workflow__steps">
        {STEPS.map((step, index) => {
          const isActive = index === active;
          const isDone = done[index] && !isActive;
          const className = [
            'workflow__step',
            isActive ? 'workflow__step--active' : '',
            isDone ? 'workflow__step--done' : '',
          ]
            .filter(Boolean)
            .join(' ');

          return (
            <li
              key={step.key}
              className={className}
              aria-current={isActive ? 'step' : undefined}
            >
              <span className="workflow__marker" aria-hidden="true">
                {isDone ? '✓' : index + 1}
              </span>
              <span className="workflow__label">{step.label}</span>
              {/*
                The state in words as well as in the marker, for a reader who
                gets no shape and no colour. Visually hidden because the marker
                already says it to everybody else.
              */}
              {(isDone || isActive) && (
                <span className="visually-hidden">
                  {isActive ? ' — in progress' : ' — done'}
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {running && (
        <p className="workflow__status" role="status">
          <span className="spinner" aria-hidden="true" />
          {running}
        </p>
      )}
    </div>
  );
}
