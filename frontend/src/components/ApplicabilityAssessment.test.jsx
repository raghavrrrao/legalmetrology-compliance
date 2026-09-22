/**
 * The assessment card renders the backend's verdict on the classification and
 * asks only what is open. It decides nothing: every state here is a wire
 * shape the backend sent, mapped once by the service.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ApplicabilityAssessment } from './ApplicabilityAssessment.jsx';
import { mapAssessment } from '../services/complianceService.js';
import { assessedFactBody, assessmentBody } from '../test/fixtures.js';

/** Through the real mapper, so the wire shape is what is under test. */
async function mapped(overrides = {}) {
  return mapAssessment(assessmentBody(overrides));
}

describe('ApplicabilityAssessment', () => {
  it('renders nothing for a backend that predates the field', () => {
    const { container } = render(<ApplicabilityAssessment assessment={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows an uncertain classification as a suggestion with one question', async () => {
    const onConfirmCategory = vi.fn();
    render(
      <ApplicabilityAssessment
        assessment={await mapped()}
        onConfirmCategory={onConfirmCategory}
        onConfirmFact={vi.fn()}
      />,
    );

    expect(screen.getByText('Needs your confirmation')).toBeInTheDocument();
    expect(screen.getByTestId('assessment-category')).toHaveTextContent(/not established/i);

    // The suggestion is labelled a suggestion, and the number is labelled as
    // the classifier's confidence in the product type - never as compliance.
    const proposal = screen.getByTestId('assessment-proposal');
    expect(proposal).toHaveTextContent(/Suggested product type/i);
    expect(proposal).toHaveTextContent(/Packaged non-food/i);
    expect(proposal).toHaveTextContent(/a suggestion from the label classifier, not an established fact/i);
    expect(proposal).toHaveTextContent(/Classifier confidence/i);
    expect(proposal).toHaveTextContent('72%');
    expect(proposal).toHaveTextContent(/not a compliance figure/i);
    expect(screen.getByTestId('assessment-proposal-reason')).toHaveTextContent(
      /not accepted for automatic use/i,
    );

    const question = screen.getByTestId('category-question');
    expect(question).toHaveTextContent('The label reads like packaged non-food. Is that right?');
    fireEvent.click(screen.getByRole('button', { name: /yes, packaged non-food/i }));
    expect(onConfirmCategory).toHaveBeenCalledWith('packaged-non-food');

    fireEvent.click(screen.getByRole('button', { name: /^packaged food$/i }));
    expect(onConfirmCategory).toHaveBeenLastCalledWith('packaged-food');
  });

  it('says plainly when the policy established the category automatically', async () => {
    render(
      <ApplicabilityAssessment
        assessment={await mapped({
          status: 'confident',
          policy: { accepted: true, min_confidence: 0.85, evaluation: 'docs/ml/evaluations/example.md' },
          category: {
            proposed: 'packaged-non-food',
            proposed_name: 'Packaged non-food',
            confidence: 0.9,
            in_effect: 'packaged-non-food',
            in_effect_source: 'classifier',
            disposition: 'established_automatically',
            reason: 'Established automatically.',
          },
          questions: [],
        })}
        onConfirmCategory={vi.fn()}
        onConfirmFact={vi.fn()}
      />,
    );

    expect(screen.getByText('Established automatically')).toBeInTheDocument();
    expect(screen.getByTestId('assessment-category')).toHaveTextContent(/established automatically from the label/i);
    const notice = screen.getByTestId('assessment-automatic');
    expect(notice).toHaveTextContent(/chosen by the label classifier/i);
    expect(notice).toHaveTextContent(/tfidf-logreg 0.1.0/);
    expect(notice).toHaveTextContent(/docs\/ml\/evaluations\/example.md/);
    expect(notice).toHaveTextContent(/selected which rules were checked/i);
    expect(screen.queryByTestId('category-question')).not.toBeInTheDocument();
    expect(screen.getByTestId('assessment-settled')).toBeInTheDocument();
  });

  it('shows an unknown classification with the generic question', async () => {
    render(
      <ApplicabilityAssessment
        assessment={await mapped({
          status: 'unknown',
          reason: 'The classifier could not tell what kind of product this is: insufficient text.',
          category: {
            proposed: null,
            proposed_name: null,
            confidence: null,
            in_effect: null,
            in_effect_source: null,
            disposition: 'not_proposed',
            reason: 'The classifier could not tell what kind of product this is: insufficient text.',
          },
          questions: [
            {
              kind: 'category',
              code: null,
              suggested: null,
              prompt: 'What kind of product is this?',
              choices: [
                { code: 'packaged-food', name: 'Packaged food' },
                { code: 'packaged-non-food', name: 'Packaged non-food' },
              ],
            },
          ],
        })}
        onConfirmCategory={vi.fn()}
        onConfirmFact={vi.fn()}
      />,
    );

    expect(screen.getByText('Could not tell')).toBeInTheDocument();
    expect(screen.getByTestId('assessment-no-proposal')).toHaveTextContent(/insufficient text/);
    expect(screen.getByTestId('category-question')).toHaveTextContent('What kind of product is this?');
    // No suggestion, so no choice is presented as "yes".
    expect(screen.queryByRole('button', { name: /^yes,/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Packaged food' })).toBeInTheDocument();
  });

  it('reports a contradiction without changing anything', async () => {
    render(
      <ApplicabilityAssessment
        assessment={await mapped({
          category: {
            proposed: 'packaged-non-food',
            proposed_name: 'Packaged non-food',
            confidence: 0.99,
            in_effect: 'packaged-food',
            in_effect_source: 'submitter',
            disposition: 'contradicted_by_submitter',
            reason: "A person stated 'packaged-food'; the classifier suggested 'packaged-non-food'.",
          },
          questions: [],
        })}
        onConfirmCategory={vi.fn()}
        onConfirmFact={vi.fn()}
      />,
    );

    expect(screen.getByTestId('assessment-category')).toHaveTextContent('packaged-food');
    expect(screen.getByTestId('assessment-category')).toHaveTextContent(/stated by you/i);
    expect(screen.getByTestId('assessment-proposal-reason')).toHaveTextContent(
      /you stated packaged-food instead/i,
    );
    expect(screen.queryByTestId('category-question')).not.toBeInTheDocument();
  });

  it('asks about a suggested fact and sends the answer a person gives', async () => {
    const onConfirmFact = vi.fn();
    render(
      <ApplicabilityAssessment
        assessment={await mapped({
          category: {
            proposed: 'packaged-non-food',
            proposed_name: 'Packaged non-food',
            confidence: 0.72,
            in_effect: 'packaged-non-food',
            in_effect_source: 'submitter',
            disposition: 'confirmed_by_submitter',
            reason: 'A person stated it.',
          },
          facts: [assessedFactBody()],
          questions: [
            {
              kind: 'condition',
              code: 'cosmetics-and-toiletries',
              suggested: 'yes',
              prompt: 'Is this package soaps, shampoos, toothpastes and other cosmetics and toiletries? The label suggests it may be.',
              choices: [],
            },
          ],
        })}
        onConfirmCategory={vi.fn()}
        onConfirmFact={onConfirmFact}
      />,
    );

    expect(screen.getByTestId('assessment-facts')).toHaveTextContent(/suggested by the label \(56%\), not yet confirmed — treated as not known/i);
    expect(screen.getByTestId('assessment-facts')).toHaveTextContent(/6\(1\)\(d\): exempts/);

    const question = screen.getByTestId('fact-question-cosmetics-and-toiletries');
    fireEvent.click(question.querySelector('button.button--primary'));
    expect(onConfirmFact).toHaveBeenCalledWith('cosmetics-and-toiletries', 'yes');
    fireEvent.click(screen.getByRole('button', { name: 'Not sure' }));
    expect(onConfirmFact).toHaveBeenLastCalledWith('cosmetics-and-toiletries', 'unknown');
  });

  it('shows open questions without buttons when there is nothing to answer them with', async () => {
    render(<ApplicabilityAssessment assessment={await mapped()} />);

    expect(screen.getByTestId('category-question-open')).toHaveTextContent(/answered from a new scan/i);
    expect(screen.queryByRole('button', { name: /yes,/i })).not.toBeInTheDocument();
  });

  it('shows the phrases the reading contains, with the words around them', async () => {
    render(<ApplicabilityAssessment assessment={await mapped()} />);

    const panel = screen.getByTestId('assessment-evidence');
    expect(panel).toHaveTextContent('What the label says');
    const signals = screen.getByTestId('assessment-label-signals');
    expect(signals).toHaveTextContent('soap / bathing bar');
    expect(signals).toHaveTextContent('typically found on: cosmetics-and-toiletries');
    // The snippet is what makes it checkable against the photograph.
    expect(signals).toHaveTextContent('…dove beauty bathing bar moisturising cream…');
    expect(panel).toHaveTextContent(/does not establish what the product is/i);

    const fields = screen.getByTestId('assessment-declared-fields');
    expect(fields).toHaveTextContent('Net quantity: Net Qty: 100 g');
    expect(panel).toHaveTextContent(/not evidence of the product type/i);
  });

  it('says plainly when the label offered nothing to go on', async () => {
    render(
      <ApplicabilityAssessment
        assessment={await mapped({
          evidence: {
            has_supporting_evidence: false,
            note: 'The label was read, but none of the phrases this system recognises as indicating a kind of product was found in it, and no declaration was extracted. There is no evidence from the label behind this suggestion.',
            label_signals: [],
            declared_fields: [],
            model_terms: [],
          },
        })}
      />,
    );

    expect(screen.queryByTestId('assessment-evidence')).not.toBeInTheDocument();
    expect(screen.getByTestId('assessment-evidence-empty')).toHaveTextContent(
      /no evidence from the label behind this suggestion/i,
    );
  });

  it('renders the empty state for a backend that reports no evidence at all', async () => {
    const { evidence: _omitted, ...older } = assessmentBody();
    render(<ApplicabilityAssessment assessment={mapAssessment(older)} />);

    expect(screen.getByTestId('assessment-evidence-empty')).toHaveTextContent(
      /no supporting evidence from the label was reported/i,
    );
  });

  it('keeps the model’s own terms out of the evidence and inside the technical detail', async () => {
    render(<ApplicabilityAssessment assessment={await mapped()} />);

    const evidence = screen.getByTestId('assessment-evidence');
    expect(evidence).not.toHaveTextContent('bathing</code>');
    const technical = screen.getByTestId('assessment-technical');
    expect(technical).toHaveTextContent(/How this suggestion was produced/i);
    expect(technical).toHaveTextContent(/internals, not statements about the product/i);
    expect(technical).toHaveTextContent(/not accepted for automatic use on this server/i);
    expect(screen.getByTestId('assessment-model-terms')).toHaveTextContent('bathing');
  });

  it('says what answering the question will do', async () => {
    render(
      <ApplicabilityAssessment
        assessment={await mapped()}
        onConfirmCategory={vi.fn()}
        onConfirmFact={vi.fn()}
      />,
    );

    const outcome = screen.getByTestId('category-question-outcome');
    expect(outcome).toHaveTextContent(/selects the requirements loaded for that product type/i);
    expect(outcome).toHaveTextContent(/not uploaded or read again/i);
    expect(outcome).toHaveTextContent(/recorded as yours/i);
    expect(outcome).toHaveTextContent(/not known rather than assuming one/i);
  });

  it('says what answering a fact question will do', async () => {
    render(
      <ApplicabilityAssessment
        assessment={await mapped({
          category: {
            proposed: 'packaged-non-food',
            proposed_name: 'Packaged non-food',
            confidence: 0.72,
            in_effect: 'packaged-non-food',
            in_effect_source: 'submitter',
            disposition: 'confirmed_by_submitter',
            reason: 'A person stated it.',
          },
          facts: [assessedFactBody()],
          questions: [
            {
              kind: 'condition',
              code: 'cosmetics-and-toiletries',
              suggested: 'yes',
              prompt: 'Is this package soaps, shampoos, toothpastes and other cosmetics and toiletries? The label suggests it may be.',
              outcome:
                'Answering decides whether clause 6(1)(d), 6(8) is checked against this package, on this same reading. The answer is recorded as yours, not as the classifier’s.',
              choices: [],
            },
          ],
        })}
        onConfirmCategory={vi.fn()}
        onConfirmFact={vi.fn()}
      />,
    );

    expect(screen.getByTestId('fact-question-outcome-cosmetics-and-toiletries')).toHaveTextContent(
      /clause 6\(1\)\(d\), 6\(8\) is checked against this package/i,
    );
  });

  it('never shows the classifier status as a compliance status', async () => {
    const { container } = render(
      <ApplicabilityAssessment assessment={await mapped({ status: 'confident', questions: [] })} />,
    );
    expect(container.textContent).not.toMatch(/\bcompliant\b/i);
  });
});
