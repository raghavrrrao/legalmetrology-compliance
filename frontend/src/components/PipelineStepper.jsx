import { PHASES } from '../hooks/useLabelAnalysis.js';

/**
 * Where the analysis has got to.
 *
 * The Figma mobile header's Upload › Analyze › Extract › Findings strip, driven
 * by the flow's real phase rather than by a timer. Its steps are the pipeline's
 * actual stages, so "Evaluate" only lights up once the reading exists and there
 * is genuinely a compliance request in flight.
 *
 * It is also the loading state for both requests: rather than one
 * indeterminate "working…", the user can see which of the two calls is running,
 * which is the difference between "OCR is slow" and "the rule engine is slow".
 */
const STEPS = [
  { key: 'upload', label: 'Upload' },
  { key: 'extract', label: 'Read label' },
  { key: 'evaluate', label: 'Check rules' },
  { key: 'findings', label: 'Findings' },
];

/** How far the flow has got, as an index into STEPS. */
const REACHED_BY_PHASE = {
  [PHASES.IDLE]: 0,
  [PHASES.EXTRACTING]: 1,
  [PHASES.EXTRACTED]: 2,
  [PHASES.EVALUATING]: 2,
  [PHASES.COMPLETE]: 3,
};

/** Which step is actively running, or -1 when nothing is in flight. */
const ACTIVE_BY_PHASE = {
  [PHASES.EXTRACTING]: 1,
  [PHASES.EVALUATING]: 2,
};

export function PipelineStepper({ phase }) {
  const reached = REACHED_BY_PHASE[phase] ?? 0;
  const active = ACTIVE_BY_PHASE[phase] ?? -1;

  return (
    <ol className="stepper" aria-label="Analysis progress">
      {STEPS.map((step, index) => {
        const isActive = index === active;
        const isDone = index < reached && !isActive;
        const className = [
          'stepper__step',
          isActive ? 'stepper__step--active' : '',
          isDone ? 'stepper__step--done' : '',
        ]
          .filter(Boolean)
          .join(' ');

        return (
          <li
            key={step.key}
            className={className}
            aria-current={isActive ? 'step' : undefined}
          >
            <span className="stepper__marker" aria-hidden="true">
              {isDone ? '✓' : index + 1}
            </span>
            {step.label}
            {isActive && (
              <>
                {' '}
                <span className="spinner" aria-hidden="true" />
                <span className="visually-hidden">in progress</span>
              </>
            )}
          </li>
        );
      })}
    </ol>
  );
}
