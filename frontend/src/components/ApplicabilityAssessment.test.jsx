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
    expect(screen.getByTestId('assessment-proposal')).toHaveTextContent(/reads like packaged non-food/i);
    expect(screen.getByTestId('assessment-proposal')).toHaveTextContent(/72% confidence about the product type/i);
    expect(screen.getByTestId('assessment-proposal')).toHaveTextContent(/not a compliance figure/i);

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
    expect(screen.getByTestId('assessment-proposal')).toHaveTextContent(/you stated packaged-food instead/i);
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

  it('never shows the classifier status as a compliance status', async () => {
    const { container } = render(
      <ApplicabilityAssessment assessment={await mapped({ status: 'confident', questions: [] })} />,
    );
    expect(container.textContent).not.toMatch(/\bcompliant\b/i);
  });
});
