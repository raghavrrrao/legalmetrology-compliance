import { StatusBadge } from './StatusBadge.jsx';
import { formatConfidence } from '../utils/compliance.js';
import { humaniseCode } from '../utils/format.js';

/**
 * What the label classifier proposed, what became of it, and what is left to
 * confirm - `applicability_assessment` on a compliance result.
 *
 * Four things this component is careful to keep true, because each is a way a
 * model's guess could be mistaken for a legal fact:
 *
 * 1. **A suggestion is labelled a suggestion.** The card says "the label reads
 *    like…" and shows the classifier's own confidence *about the product
 *    type*, in words that say it is not a compliance figure.
 * 2. **Automatic is labelled automatic.** When the backend's accepted policy
 *    established the category without a person, the card says so, names the
 *    classifier and the policy, and says which rules it selected - so nobody
 *    reads a set of findings without knowing a model chose the rule set.
 * 3. **Only the questions that are open are asked.** `questions` is what the
 *    backend says a person still has to answer; a settled fact produces no
 *    button. Confirming a category or a fact re-runs the rules over the same
 *    reading through the callbacks the page already has for the manual path.
 * 4. **Nothing is decided here.** Every status, disposition and question is
 *    the backend's; this component renders them. The backend's `status` is
 *    the policy's reliability verdict (`confident`, `uncertain`, `unknown`,
 *    `failed`), and it is shown as that, never rounded to a compliance state.
 * 5. **The evidence is the reading, not the model.** Phrases found in the
 *    photograph's own text are shown with the surrounding words, so the person
 *    being asked can check them against the label in seconds. When there is no
 *    such evidence the card says so in a sentence rather than leaving an empty
 *    space that reads as "nothing to worry about". The model's own terms stay
 *    in the technical disclosure, labelled as internals - they explain how the
 *    model weighed the text, and they are not facts about the product.
 *
 * Status is never carried by colour alone: every state has a word in the badge
 * and a sentence in the body.
 */

const STATUS_TONE = Object.freeze({
  confident: 'success',
  uncertain: 'review',
  unknown: 'muted',
  failed: 'muted',
});

const STATUS_LABEL = Object.freeze({
  confident: 'Established automatically',
  uncertain: 'Needs your confirmation',
  unknown: 'Could not tell',
  failed: 'No classification',
});

const SOURCE_LABEL = Object.freeze({
  submitter: 'stated by you',
  reviewer: 'recorded by a reviewer',
  classifier: 'established automatically from the label',
});

export function ApplicabilityAssessment({
  assessment,
  disabled,
  onConfirmCategory,
  onConfirmFact,
}) {
  if (!assessment) {
    return null;
  }

  const { status, category, facts, questions, classifier, policy, evidence } = assessment;
  // Without handlers - a stored result reopened from a link - the questions
  // are shown as open, not as buttons that would lead nowhere.
  const canAnswer = Boolean(onConfirmCategory && onConfirmFact);
  const categoryQuestion = questions.find((q) => q.kind === 'category') ?? null;
  const factQuestions = questions.filter((q) => q.kind === 'condition');

  return (
    <section
      className="card card--assessment"
      aria-labelledby="assessment-title"
      data-testid="applicability-assessment"
    >
      <div className="card__header">
        <h2 className="card__title" id="assessment-title">
          What kind of product this is
        </h2>
        <StatusBadge
          value={status}
          tone={STATUS_TONE[status] ?? 'neutral'}
          label={STATUS_LABEL[status]}
        />
      </div>

      <div className="card__body">
        {/* --- the category ------------------------------------------------ */}
        {category.inEffect ? (
          <p data-testid="assessment-category">
            <strong>Product type used for this check:</strong>{' '}
            {category.inEffect}{' '}
            <span className="hint">
              ({SOURCE_LABEL[category.inEffectSource] ?? category.inEffectSource})
            </span>
          </p>
        ) : (
          <p data-testid="assessment-category">
            <strong>Product type used for this check:</strong> not established —
            the rules for a specific product type were not applied.
          </p>
        )}

        {category.disposition === 'established_automatically' && (
          <p className="panel panel--warning" data-testid="assessment-automatic">
            The product type was chosen by the label classifier (
            {classifier.name} {classifier.version}, confidence{' '}
            {formatConfidence(classifier.confidence)} about the product type)
            under this installation&rsquo;s accepted policy
            {policy.evaluation ? ` (${policy.evaluation})` : ''}. It selected
            which rules were checked. If it is wrong, choose the right type
            below and the rules will be checked again.
          </p>
        )}

        {category.proposed && category.disposition !== 'established_automatically' && (
          <>
            <dl className="suggestion" data-testid="assessment-proposal">
              <dt>Suggested product type</dt>
              <dd>
                <strong>{category.proposedName ?? category.proposed}</strong>{' '}
                <span className="hint">
                  — a suggestion from the label classifier, not an established fact
                </span>
              </dd>
              <dt>Classifier confidence</dt>
              <dd>
                {formatConfidence(category.confidence) ?? 'Not reported'}{' '}
                <span className="hint">
                  in the <em>product type</em>. This is not a compliance figure, and no
                  compliance figure can be derived from it.
                </span>
              </dd>
            </dl>
            <p className="hint" data-testid="assessment-proposal-reason">
              {category.disposition === 'confirmed_by_submitter' && 'You confirmed it.'}
              {category.disposition === 'contradicted_by_submitter' &&
                `You stated ${category.inEffect} instead; your statement is what was checked.`}
              {category.disposition === 'needs_confirmation' && category.reason}
            </p>
          </>
        )}

        {/*
          What the photograph actually says. Shown whenever the card is asking
          for something, and for a settled suggestion too - a person reading a
          result later needs the same basis the answer was given on.
        */}
        <EvidencePanel evidence={evidence} />

        {!category.proposed && !category.inEffect && (
          <p className="hint" data-testid="assessment-no-proposal">{category.reason}</p>
        )}

        {categoryQuestion && !canAnswer && (
          <p className="hint" data-testid="category-question-open">
            <strong>{categoryQuestion.prompt}</strong> This can be answered from a
            new scan of the same photo.
          </p>
        )}

        {categoryQuestion && canAnswer && (
          <div className="question" data-testid="category-question">
            <p className="question__legend">
              <strong>{categoryQuestion.prompt}</strong>
            </p>
            <div className="question__options">
              {categoryQuestion.choices.map((choice) => (
                <button
                  key={choice.code}
                  type="button"
                  className={`button${
                    choice.code === categoryQuestion.suggested ? ' button--primary' : ''
                  }`}
                  disabled={disabled}
                  onClick={() => onConfirmCategory(choice.code)}
                >
                  {choice.code === categoryQuestion.suggested
                    ? `Yes, ${choice.name.toLowerCase()}`
                    : choice.name}
                </button>
              ))}
            </div>
            <p className="hint" data-testid="category-question-outcome">
              {categoryQuestion.outcome}
            </p>
          </div>
        )}

        {/* --- facts a subcategory suggested ---------------------------------- */}
        {facts.length > 0 && (
          <ul className="assessment-facts" data-testid="assessment-facts">
            {facts.map((fact) => (
              <li key={fact.condition}>
                <strong>{fact.name}:</strong>{' '}
                {fact.disposition === 'needs_confirmation' &&
                  `suggested by the label (${formatConfidence(fact.confidence)}), not yet confirmed — treated as not known.`}
                {fact.disposition === 'confirmed_by_submitter' && 'confirmed by you.'}
                {fact.disposition === 'contradicted_by_submitter' &&
                  'you answered no; your answer is what was checked.'}
                {fact.disposition === 'not_proposed' && fact.reason}
                {fact.affects.length > 0 && (
                  <span className="hint"> Bears on clause {fact.affects.join(', ')}.</span>
                )}
              </li>
            ))}
          </ul>
        )}

        {canAnswer && factQuestions.map((question) => (
          <div className="question" key={question.code} data-testid={`fact-question-${question.code}`}>
            <p className="question__legend">
              <strong>{question.prompt}</strong>
            </p>
            <div className="question__options">
              <button
                type="button"
                className="button button--primary"
                disabled={disabled}
                onClick={() => onConfirmFact(question.code, 'yes')}
              >
                Yes
              </button>
              <button
                type="button"
                className="button"
                disabled={disabled}
                onClick={() => onConfirmFact(question.code, 'no')}
              >
                No
              </button>
              <button
                type="button"
                className="button"
                disabled={disabled}
                onClick={() => onConfirmFact(question.code, 'unknown')}
              >
                Not sure
              </button>
            </div>
            {question.outcome && (
              <p className="hint" data-testid={`fact-question-outcome-${question.code}`}>
                {question.outcome}
              </p>
            )}
          </div>
        ))}

        {questions.length === 0 && (
          <p className="hint" data-testid="assessment-settled">
            Nothing here needs your confirmation.
          </p>
        )}

        <details className="technical-details" data-testid="assessment-technical">
          <summary>How this suggestion was produced</summary>
          <p className="hint">{assessment.reason}</p>
          <p className="hint">
            Classifier: {classifier.name} {classifier.version}
            {policy.accepted
              ? ` · accepted for automatic use above ${formatConfidence(policy.minConfidence)}${
                  policy.evaluation ? ` (${policy.evaluation})` : ''
                }`
              : ' · not accepted for automatic use on this server'}
          </p>
          {evidence.modelTerms.length > 0 && (
            <>
              <p className="hint">
                Terms the model weighed most in this text. These are the model&rsquo;s
                internals, not statements about the product — on a small training set
                they include ordinary words.
              </p>
              <ul className="hint" data-testid="assessment-model-terms">
                {evidence.modelTerms.map((term) => (
                  <li key={term}>
                    <code>{term}</code>
                  </li>
                ))}
              </ul>
            </>
          )}
        </details>
      </div>
    </section>
  );
}

/**
 * The reading behind the suggestion: phrases this photograph's text contains,
 * and the declarations the extractor read off it.
 *
 * Two rules, both of which are the point of the panel:
 *
 * - **Nothing is displayed that is not in the reading.** Every phrase comes
 *   from the backend with the surrounding words it was found in, and the
 *   declarations are what the extractor read. There is no generated
 *   explanation of the model's reasoning here.
 * - **"No evidence" is a state, stated.** An empty panel would read as
 *   reassurance. The backend's own sentence says what was missing.
 */
function EvidencePanel({ evidence }) {
  if (!evidence) {
    return null;
  }

  if (!evidence.hasSupportingEvidence) {
    return (
      <div className="evidence-panel" data-testid="assessment-evidence-empty">
        <h3 className="evidence-panel__title">What the label says</h3>
        <p className="hint">
          {evidence.note ||
            'No supporting evidence from the label was reported for this suggestion.'}
        </p>
      </div>
    );
  }

  return (
    <div className="evidence-panel" data-testid="assessment-evidence">
      <h3 className="evidence-panel__title">What the label says</h3>

      {evidence.labelSignals.length > 0 && (
        <>
          <p className="hint">
            Phrases found in the text read from this photograph. Each is shown with the
            words around it so you can check it against the label. A phrase is
            <em> typically</em> found on this kind of product — it does not establish
            what the product is.
          </p>
          <ul className="evidence-list" data-testid="assessment-label-signals">
            {evidence.labelSignals.map((signal) => (
              <li key={signal.phrase}>
                <strong>{signal.phrase}</strong>{' '}
                <span className="hint">typically found on: {signal.indicativeOf}</span>
                <q className="evidence-list__snippet">{signal.snippet}</q>
              </li>
            ))}
          </ul>
        </>
      )}

      {evidence.declaredFields.length > 0 && (
        <>
          <p className="hint">
            Declarations the reader extracted from the same photograph. Context for
            whether the label was understood — not evidence of the product type.
          </p>
          <ul className="evidence-list" data-testid="assessment-declared-fields">
            {evidence.declaredFields.map((field) => (
              <li key={field.fieldKey}>
                <strong>{humaniseCode(field.fieldKey)}:</strong> {field.value}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
