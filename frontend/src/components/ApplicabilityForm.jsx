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
 *    "Not answered", and that is not an answer — the engine treats it exactly
 *    as it treats silence. Defaulting a radio group to "No" would silently
 *    assert facts about somebody's product.
 * 2. **"Not sure" is a distinct, offerable answer.** It records that somebody
 *    was asked. It has the same effect on the engine as silence and the form
 *    says so, rather than quietly folding it into "No".
 * 3. **The consequence of leaving a question unanswered is stated up front**,
 *    because a user who does not know that silence costs a REVIEW REQUIRED
 *    cannot make an informed choice about answering.
 *
 * **Seventeen questions is the problem this layout solves.** Presented as one
 * column of statutory prose it reads as a wall and gets abandoned, which costs
 * the user the very reviews it exists to resolve. So: four collapsed group
 * cards, each opening to short questions with three buttons, and the legal
 * apparatus — the clause, the mode, the framework's note — one further
 * disclosure down under "Why are we asking?". Nothing is removed and nothing is
 * rewritten; what changed is the order it arrives in. The count is reported as
 * progress ("3 of 17 answered"), never as a demand.
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
      <Shell>
        <p className="hint">
          <span className="spinner" aria-hidden="true" /> Loading the facts this
          installation can use…
        </p>
      </Shell>
    );
  }

  if (error) {
    return (
      <Shell>
        <p className="hint">
          The list of questions could not be loaded ({error.message}). You can
          still analyse a label — anything that depends on one of these facts
          will be reported as <strong>needing review</strong>, which is a
          correct result rather than a failure.
        </p>
      </Shell>
    );
  }

  if (!catalogue || catalogue.conditions.length === 0) {
    return (
      <Shell>
        <p className="hint">
          {catalogue && !catalogue.frameworkLoaded
            ? 'The legal framework is not loaded in this installation, so no declaration could affect a result. Run `manage.py load_legal_framework` on the backend.'
            : 'No declarable fact bears on any rule currently loaded, so there is nothing to state here.'}
        </p>
      </Shell>
    );
  }

  const groups = groupConditions(catalogue.conditions);
  const total = catalogue.conditions.length;
  const answeredCount = Object.values(answers).filter(Boolean).length;

  return (
    <Shell answeredCount={answeredCount} total={total}>
      <p className="lede-text">
        Some requirements depend on facts a photograph cannot show — what is
        inside the package, who it is sold to, where it came from.
      </p>
      <p className="hint">
        <strong>These questions are optional. Answer what you know.</strong>{' '}
        Anything left unanswered stays <em>not established</em>, and a
        requirement that depends on it is reported as{' '}
        <strong>requires review</strong> rather than being guessed either way.
      </p>

      {catalogue.answerSemantics?.unknown && (
        <details className="technical-details">
          <summary>What does “Not sure” do?</summary>
          <p>{catalogue.answerSemantics.unknown}</p>
        </details>
      )}

      <div className="question-groups">
        {groups.map((group) => (
          <ConditionGroup
            key={group.key}
            group={group}
            answers={answers}
            onChange={onChange}
            disabled={disabled}
          />
        ))}
      </div>

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
    </Shell>
  );
}

/** The card every state of this form renders inside, so they cannot drift. */
function Shell({ children, answeredCount = 0, total = 0 }) {
  return (
    <section className="card card--questions">
      <div className="card__header">
        <h2 className="card__title">Tell us about this package</h2>
        {total > 0 && (
          <span
            className={`answered-chip${answeredCount > 0 ? ' answered-chip--some' : ''}`}
          >
            {answeredCount} of {total} answered
          </span>
        )}
      </div>
      <div className="card__body">{children}</div>
    </section>
  );
}

/**
 * The groups, and the only thing in this file that comes close to legal
 * knowledge.
 *
 * It is not legal knowledge: `mode` is the API's own vocabulary for what an
 * answer *does* to a clause, served on every `affects` entry alongside a
 * `mode_display` the backend writes. These headings say the same thing in the
 * words a submitter uses, so seventeen questions arrive as four short groups
 * instead of one list. **No condition is assigned to a group by its code, its
 * name or its subject matter** — only by the effect the API says it has. Add a
 * condition to the framework and it groups itself.
 *
 * Ordered as a submitter meets them: does this even apply to me, what kind of
 * product is it, is anything unusual about it, where did it come from.
 */
const GROUPS = [
  {
    key: 'scope_gate',
    mode: 'scope_gate',
    eyebrow: 'Package scope',
    heading: 'Does any scope exclusion apply to this package?',
    lede:
      'Some types of packages are outside the scope of these Rules. Answer “Yes” only if one of these describes your package. If you are unsure, choose “Not sure”.',
  },
  {
    key: 'withholds_exemption',
    mode: 'withholds_exemption',
    eyebrow: 'Product type',
    heading: 'Does this package belong to a special product category?',
    lede:
      'These product types cannot rely on an exemption that might otherwise excuse a declaration.',
  },
  {
    key: 'exempts',
    mode: 'exempts',
    eyebrow: 'Special circumstances',
    heading: 'Does a special exemption apply?',
    lede:
      'Each of these excuses the package from one particular declaration. The rest of the check stands either way.',
  },
  {
    key: 'requires',
    mode: 'requires',
    eyebrow: 'Import information',
    heading: 'Where did this product come from?',
    lede: 'These facts make an additional declaration required.',
  },
];

const OTHER_GROUP = {
  key: 'other',
  eyebrow: 'Other',
  heading: 'Anything else we should know?',
  lede:
    'These affect the check in a way this version of the screen has no plainer description for. Open “Why are we asking?” under a question for what the backend says it does.',
};

/**
 * Sort the served conditions into the groups above, by their declared effect.
 *
 * A condition is placed by the first mode in `GROUPS` that appears anywhere in
 * its `affects`, so a condition carrying more than one effect lands under the
 * broadest one rather than being listed twice. Anything whose mode this build
 * does not recognise — including a condition with no `affects` at all — goes to
 * `OTHER_GROUP` and is still asked. A question the API served is never dropped
 * for being unfamiliar; being unfamiliar is not a reason to stop asking it.
 */
function groupConditions(conditions) {
  const buckets = new Map();

  for (const condition of conditions) {
    const modes = new Set((condition.affects ?? []).map((effect) => effect.mode));
    const group =
      GROUPS.find((candidate) => modes.has(candidate.mode)) ?? OTHER_GROUP;
    if (!buckets.has(group.key)) {
      buckets.set(group.key, []);
    }
    buckets.get(group.key).push(condition);
  }

  return [...GROUPS, OTHER_GROUP]
    .filter((group) => buckets.has(group.key))
    .map((group) => ({ ...group, conditions: buckets.get(group.key) }));
}

/**
 * One group, collapsed until asked for.
 *
 * `<details>` rather than a state-driven panel: it opens without JavaScript,
 * it is keyboard-operable and announced correctly for free, and the browser's
 * find-in-page can still reach the questions inside a closed one.
 */
function ConditionGroup({ group, answers, onChange, disabled }) {
  const answeredHere = group.conditions.filter(
    (condition) => answers[condition.code],
  ).length;

  return (
    <details className="question-group">
      <summary className="question-group__summary">
        <span className="question-group__text">
          <span className="question-group__eyebrow">{group.eyebrow}</span>
          <span className="question-group__heading">{group.heading}</span>
        </span>
        <span className="question-group__count">
          {answeredHere > 0
            ? `${answeredHere} of ${group.conditions.length} answered`
            : `${group.conditions.length} question${group.conditions.length === 1 ? '' : 's'}`}
        </span>
      </summary>

      <div className="question-group__body">
        <p className="hint">{group.lede}</p>
        {group.conditions.map((condition) => (
          <ConditionField
            key={condition.code}
            condition={condition}
            value={answers[condition.code] ?? ''}
            onChange={onChange}
            disabled={disabled}
          />
        ))}
      </div>
    </details>
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
 *
 * The description is the framework's own prose and can run to several sentences
 * of statutory reference. Its first sentence leads, as the short explanation a
 * submitter needs in order to answer; the whole of it, unedited, is one
 * disclosure away. Nothing is truncated out of existence.
 */
function ConditionField({ condition, value, onChange, disabled }) {
  const name = `applicability-${condition.code}`;
  const describedBy = `${name}-help`;
  const summary = leadSentence(condition.description);
  const hasMoreDetail =
    Boolean(condition.description && condition.description !== summary) ||
    Boolean(condition.determinationNote) ||
    condition.affects.length > 0;

  return (
    <fieldset className="question" disabled={disabled}>
      <legend className="question__legend">{condition.name}</legend>

      {summary && (
        <p className="question__help" id={describedBy}>
          {summary}
        </p>
      )}

      <div className="question__options">
        {/*
          The unanswered option is a real radio, not the absence of one. A group
          with no checked option cannot be cleared by keyboard once an answer is
          picked, and "Not answered" has to be as reachable as the answers.
        */}
        <label className="question__option question__option--none">
          <input
            type="radio"
            name={name}
            value=""
            checked={value === ''}
            aria-describedby={summary ? describedBy : undefined}
            onChange={() => onChange(condition.code, '')}
          />
          <span>Not answered</span>
        </label>

        {condition.answers.map((answer) => (
          <label className="question__option" key={answer}>
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

      {hasMoreDetail && (
        <details className="question__why">
          <summary>Why are we asking?</summary>

          {condition.description && condition.description !== summary && (
            <p>{condition.description}</p>
          )}

          {condition.affects.length > 0 && (
            <ul className="question__effects">
              {condition.affects.map((effect) => (
                <li key={`${effect.clause}-${effect.mode}`}>
                  <strong>Rule {effect.clause}</strong>
                  {effect.modeDisplay && ` — ${effect.modeDisplay}`}
                  {effect.note && `: ${effect.note}`}
                </li>
              ))}
            </ul>
          )}

          {condition.determinationNote && (
            <p className="is-muted">{condition.determinationNote}</p>
          )}
        </details>
      )}
    </fieldset>
  );
}

/**
 * The first sentence of the framework's description, as the short explanation.
 *
 * Split on sentence-ending punctuation followed by a space and a capital, which
 * leaves "rule 6(1)(e)." and "25 kg." intact — an abbreviation-blind split would
 * cut a legal reference in half and change what it says. Returns the whole
 * string when it is one sentence or when no split point is found, so the worst
 * case is the text that is there today rather than a mangled version of it.
 */
function leadSentence(description) {
  const text = (description ?? '').trim();
  if (!text) {
    return '';
  }
  const match = text.match(/^(.+?[.?!])\s+[A-Z(]/s);
  return match ? match[1] : text;
}

/**
 * Plain-English labels for the API's answer vocabulary.
 *
 * A presentation mapping and nothing more: the value sent is `answer`, taken
 * from the API's own `answers` list, and an answer this build has no label for
 * still renders and still submits. It is emphatically not a place to add a
 * fourth answer or to change what one means.
 *
 * `unknown` reads "Not sure" rather than "Don't know" because a submitter
 * recognises the first as something they are allowed to be. **The value sent is
 * still `unknown`**, and what the engine does with it is unchanged: it is never
 * read as "no".
 */
const ANSWER_LABELS = Object.freeze({
  yes: 'Yes',
  no: 'No',
  unknown: 'Not sure',
});
