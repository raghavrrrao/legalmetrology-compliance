/**
 * The declaration form.
 *
 * Three properties are asserted here and all three are safety properties
 * rather than presentation ones:
 *
 * 1. Nothing in the form is authored in the browser. Every question, clause
 *    reference and explanation comes from the API.
 * 2. Unanswered is the default, and it is not "no".
 * 3. "Don't know" is offerable and stays distinct from "no".
 *
 * The fourth thing asserted is that a broken catalogue does not cost the user
 * the ability to analyse a label - the declarations are optional, and a clause
 * that cannot be decided without one is reported as needing review, which is a
 * correct result rather than a failure.
 */

import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ApplicabilityForm } from './ApplicabilityForm.jsx';
import { applicabilityBody, applicabilityConditionBody } from '../test/fixtures.js';

/** The mapped shape the component consumes, built from the wire fixture. */
function catalogue(overrides = {}) {
  const body = applicabilityBody(overrides);
  return {
    conditions: body.conditions.map((condition) => ({
      code: condition.code,
      name: condition.name,
      description: condition.description,
      determination: condition.determination,
      determinationNote: condition.determination_note,
      scope: condition.scope,
      answers: condition.answers,
      affects: condition.affects.map((effect) => ({
        clause: effect.clause,
        mode: effect.mode,
        modeDisplay: effect.mode_display,
        note: effect.note,
        ruleCodes: effect.rule_codes,
      })),
    })),
    answerSemantics: body.answer_semantics,
    frameworkLoaded: body.framework_loaded,
  };
}

function renderForm(props = {}) {
  const onChange = vi.fn();
  const utils = render(
    <ApplicabilityForm
      catalogue={catalogue()}
      isLoading={false}
      error={null}
      answers={{}}
      onChange={onChange}
      onClearAll={vi.fn()}
      disabled={false}
      {...props}
    />,
  );
  return { ...utils, onChange };
}

/** Open the disclosure the questions live behind. */
function openQuestions() {
  fireEvent.click(screen.getByText(/state what you know about this package/i));
}

describe('states', () => {
  it('shows a loading state while the catalogue is fetched', () => {
    renderForm({ catalogue: null, isLoading: true });

    expect(screen.getByText(/loading the facts/i)).toBeInTheDocument();
  });

  it('lets the user carry on when the catalogue could not be loaded', () => {
    renderForm({
      catalogue: null,
      isLoading: false,
      error: new Error('Network unreachable'),
    });

    expect(screen.getByText(/could not be loaded/i)).toBeInTheDocument();
    expect(screen.getByText(/you can still analyse a label/i)).toBeInTheDocument();
    // And says what the cost of that is, rather than implying nothing is lost.
    expect(screen.getByText(/needing review/i)).toBeInTheDocument();
  });

  it('tells a deployment its legal framework is not loaded', () => {
    renderForm({
      catalogue: { conditions: [], answerSemantics: {}, frameworkLoaded: false },
    });

    expect(screen.getByText(/framework is not loaded/i)).toBeInTheDocument();
  });

  it('says so when nothing declarable bears on any loaded rule', () => {
    renderForm({
      catalogue: { conditions: [], answerSemantics: {}, frameworkLoaded: true },
    });

    expect(screen.getByText(/no declarable fact bears/i)).toBeInTheDocument();
  });
});

describe('the questions', () => {
  it('renders one question per condition the API served', () => {
    renderForm();
    openQuestions();

    expect(
      screen.getByRole('group', { name: /imported product/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('group', { name: /institutional consumer/i }),
    ).toBeInTheDocument();
  });

  it('separates a scope gate from a clause-level exemption', () => {
    renderForm();
    openQuestions();

    // The two behave differently: one takes the package out of the Rules
    // entirely, the other excuses a single declaration.
    expect(screen.getByText(/takes the package outside these rules/i)).toBeInTheDocument();
    expect(screen.getByText(/the rest of the check stands/i)).toBeInTheDocument();
  });

  it('shows the clause each answer would affect, in the API’s own words', () => {
    renderForm();
    openQuestions();

    const group = screen.getByRole('group', { name: /imported product/i });
    expect(within(group).getByText(/Rule 6\(1\)\(aa\)/)).toBeInTheDocument();
    expect(
      within(group).getByText(/Applies to imported products only/),
    ).toBeInTheDocument();
  });

  it('offers exactly the answers the API listed, plus an unanswered option', () => {
    renderForm();
    openQuestions();

    const group = screen.getByRole('group', { name: /imported product/i });
    const labels = within(group)
      .getAllByRole('radio')
      .map((radio) => radio.closest('label').textContent);

    expect(labels).toEqual(['Not stated', 'Yes', 'No', 'Don’t know']);
  });
});

describe('answers', () => {
  it('starts every question unanswered, and unanswered is not "no"', () => {
    renderForm();
    openQuestions();

    const group = screen.getByRole('group', { name: /imported product/i });
    expect(within(group).getByRole('radio', { name: 'Not stated' })).toBeChecked();
    expect(within(group).getByRole('radio', { name: 'No' })).not.toBeChecked();
  });

  it('reports an answer by condition code', () => {
    const { onChange } = renderForm();
    openQuestions();

    const group = screen.getByRole('group', { name: /imported product/i });
    fireEvent.click(within(group).getByRole('radio', { name: 'Yes' }));

    expect(onChange).toHaveBeenCalledWith('imported-product', 'yes');
  });

  it('keeps “don’t know” distinct from “no”', () => {
    const { onChange } = renderForm();
    openQuestions();

    const group = screen.getByRole('group', { name: /imported product/i });
    fireEvent.click(within(group).getByRole('radio', { name: 'Don’t know' }));

    // 'unknown', never 'no'. Folding the two together would silently assert a
    // fact about somebody's product.
    expect(onChange).toHaveBeenCalledWith('imported-product', 'unknown');
  });

  it('can be returned to unanswered after an answer is picked', () => {
    const { onChange } = renderForm({ answers: { 'imported-product': 'yes' } });
    openQuestions();

    const group = screen.getByRole('group', { name: /imported product/i });
    fireEvent.click(within(group).getByRole('radio', { name: 'Not stated' }));

    expect(onChange).toHaveBeenCalledWith('imported-product', '');
  });

  it('explains what leaving a question unanswered costs', () => {
    renderForm();

    expect(screen.getByText(/stays/i)).toBeInTheDocument();
    expect(screen.getAllByText(/requires review/i).length).toBeGreaterThan(0);
  });

  it('takes the meaning of “don’t know” from the API, not from itself', () => {
    renderForm();

    expect(screen.getByText(/never read as/i)).toBeInTheDocument();
  });
});

describe('what is never hardcoded', () => {
  it('renders a condition this build has never heard of', () => {
    // The proof that the catalogue is data. A condition added to the framework
    // after this build shipped has to appear without a code change.
    renderForm({
      catalogue: catalogue({
        conditions: [
          applicabilityConditionBody({
            code: 'a-condition-invented-for-this-test',
            name: 'Something no build knows about',
            description: 'Added to the framework after this build shipped.',
            affects: [],
          }),
        ],
      }),
    });
    openQuestions();

    expect(
      screen.getByRole('group', { name: /something no build knows about/i }),
    ).toBeInTheDocument();
  });
});
