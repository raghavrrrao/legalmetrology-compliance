import { humaniseCode } from '../utils/format.js';

/**
 * The facts about the package that no photograph can establish.
 *
 * Several clauses of the Rules apply — or do not apply — on facts a camera
 * cannot see: whether the package contains bidi, whether it is imported,
 * whether the buyer is an institutional consumer. Without them the engine
 * cannot decide those clauses and correctly reports REVIEW REQUIRED. This is
 * where a submitter states them.
 *
 * Everything on this form is served by
 * `GET /api/v1/compliance/applicability-conditions/`. **No condition code,
 * clause number, exemption or explanation is written in this file.** Hardcoding
 * the legal catalogue in JSX would put a copy of the law in the browser that
 * goes stale silently, which is the failure this whole project is built
 * against. If this component ever grows a literal condition code, that is a
 * bug.
 *
 * Three properties this component exists to guarantee:
 *
 * 1. **Unanswered is the default and is never "no".** Every question starts on
 *    "Not stated", and that is not an answer — the engine treats it exactly as
 *    it treats silence. Defaulting a radio group to "No" would silently assert
 *    facts about somebody's product.
 * 2. **"Don't know" is a distinct, offerable answer.** It records that somebody
 *    was asked. It has the same effect on the engine as silence and the form
 *    says so, rather than quietly folding it into "No".
 * 3. **The consequence of leaving a question unanswered is stated up front**,
 *    because a user who does not know that silence costs a REVIEW REQUIRED
 *    cannot make an informed choice about answering.
 *
 * Collapsed by default. Seventeen questions is an honest list, not a short one,
 * and a wall of radio buttons in front of the upload button would make the
 * ordinary case — a retail package with nothing unusual about it — worse.
 */
export function ApplicabilityForm({
  catalogue,
  isLoading,
  error,
  answers,
  onChange,
  onClearAll,
  disabled,
}) {
  if (isLoading) {
    return (
      <div className="card">
        <div className="card__header">
          <h2 className="card__title">About this package</h2>
        </div>
        <div className="card__body">
          <p className="hint">
            <span className="spinner" aria-hidden="true" /> Loading the facts
            this installation can use…
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <div className="card__header">
          <h2 className="card__title">About this package</h2>
        </div>
        <div className="card__body">
          <p className="hint">
            The list of declarable facts could not be loaded ({error.message}).
            You can still analyse a label — the clauses that turn on an
            undeclared fact will be reported as needing review, which is a
            correct result rather than a failure.
          </p>
        </div>
      </div>
    );
  }

  if (!catalogue || catalogue.conditions.length === 0) {
    return (
      <div className="card">
        <div className="card__header">
          <h2 className="card__title">About this package</h2>
        </div>
        <div className="card__body">
          <p className="hint">
            {catalogue && !catalogue.frameworkLoaded
              ? 'The legal framework is not loaded in this installation, so no declaration could affect a result. Run `manage.py load_legal_framework` on the backend.'
              : 'No declarable fact bears on any rule currently loaded, so there is nothing to state here.'}
          </p>
        </div>
      </div>
    );
  }

  const scopeConditions = catalogue.conditions.filter(
    (condition) => condition.scope === 'rules_scope',
  );
  const clauseConditions = catalogue.conditions.filter(
    (condition) => condition.scope !== 'rules_scope',
  );
  const answeredCount = Object.values(answers).filter(Boolean).length;

  return (
    <div className="card">
      <div className="card__header">
        <h2 className="card__title">About this package</h2>
        {answeredCount > 0 && (
          <span className="verdict__meta">{answeredCount} stated</span>
        )}
      </div>

      <div className="card__body">
        <p className="hint">
          Some clauses apply, or do not apply, on facts a photograph cannot
          show. Anything you leave unanswered stays <strong>unestablished</strong>,
          and a clause that turns on it is reported as{' '}
          <strong>requires review</strong> rather than being guessed either way.
        </p>
        {catalogue.answerSemantics?.unknown && (
          <p className="hint">
            <strong>Don’t know</strong> — {catalogue.answerSemantics.unknown}
          </p>
        )}
      </div>

      <details className="applicability">
        <summary>
          State what you know about this package ({catalogue.conditions.length}{' '}
          questions, all optional)
        </summary>

        <div className="applicability__body">
          {scopeConditions.length > 0 && (
            <ConditionGroup
              heading="Does the Rules’ scope reach this package?"
              lede="Answering “yes” to any of these takes the package outside these Rules, or outside Chapter II. Nothing would be checked against it."
              conditions={scopeConditions}
              answers={answers}
              onChange={onChange}
              disabled={disabled}
            />
          )}

          {clauseConditions.length > 0 && (
            <ConditionGroup
              heading="Does a particular declaration apply?"
              lede="These excuse the package from one declaration, or make one required. The rest of the check stands either way."
              conditions={clauseConditions}
              answers={answers}
              onChange={onChange}
              disabled={disabled}
            />
          )}

          {answeredCount > 0 && (
            <button
              type="button"
              className="button"
              onClick={onClearAll}
              disabled={disabled}
            >
              Clear all answers
            </button>
          )}
        </div>
      </details>
    </div>
  );
}

function ConditionGroup({ heading, lede, conditions, answers, onChange, disabled }) {
  return (
    <section className="applicability__group">
      <h3 className="section-heading">{heading}</h3>
      <p className="hint">{lede}</p>
      {conditions.map((condition) => (
        <ConditionField
          key={condition.code}
          condition={condition}
          value={answers[condition.code] ?? ''}
          onChange={onChange}
          disabled={disabled}
        />
      ))}
    </section>
  );
}

/**
 * One question, as a radio group with an explicit unanswered option.
 *
 * A `fieldset`/`legend` rather than a `label`, because a radio group is
 * several controls answering one question, and a screen reader needs the
 * question read with each option. The consequence of each answer is taken from
 * the API's own note on the clause link — never composed here from the mode and
 * the clause number, which would be this file describing the law.
 */
function ConditionField({ condition, value, onChange, disabled }) {
  const name = `applicability-${condition.code}`;
  const describedBy = `${name}-help`;

  return (
    <fieldset className="applicability__field" disabled={disabled}>
      <legend>{condition.name}</legend>

      {condition.description && (
        <p className="hint" id={describedBy}>
          {condition.description}
        </p>
      )}

      <div className="applicability__options">
        {/*
          The unanswered option is a real radio, not the absence of one. A group
          with no checked option cannot be cleared by keyboard once an answer is
          picked, and "Not stated" has to be as reachable as the answers.
        */}
        <label className="applicability__option">
          <input
            type="radio"
            name={name}
            value=""
            checked={value === ''}
            aria-describedby={condition.description ? describedBy : undefined}
            onChange={() => onChange(condition.code, '')}
          />
          <span>Not stated</span>
        </label>

        {condition.answers.map((answer) => (
          <label className="applicability__option" key={answer}>
            <input
              type="radio"
              name={name}
              value={answer}
              checked={value === answer}
              onChange={() => onChange(condition.code, answer)}
            />
            <span>{ANSWER_LABELS[answer] ?? humaniseCode(answer)}</span>
          </label>
        ))}
      </div>

      {condition.affects.length > 0 && (
        <ul className="applicability__effects">
          {condition.affects.map((effect) => (
            <li key={`${effect.clause}-${effect.mode}`}>
              <strong>Rule {effect.clause}</strong>
              {effect.modeDisplay && ` — ${effect.modeDisplay}`}
              {effect.note && `: ${effect.note}`}
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}

/**
 * Plain-English labels for the API's answer vocabulary.
 *
 * A presentation mapping and nothing more: the value sent is `answer`, taken
 * from the API's own `answers` list, and an answer this build has no label for
 * still renders and still submits. It is emphatically not a place to add a
 * fourth answer or to change what one means.
 */
const ANSWER_LABELS = Object.freeze({
  yes: 'Yes',
  no: 'No',
  unknown: 'Don’t know',
});
