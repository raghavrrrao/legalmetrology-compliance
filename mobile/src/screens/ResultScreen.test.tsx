/**
 * The result screen renders what the backend returned and nothing else.
 *
 * `toHaveTextContent` is used with `exact: false` throughout: it is a
 * substring check against the element's whole text, which is the question
 * being asked ("does this card say X somewhere?").
 *
 * The analysis is faked in a chosen state (see tests/render.ts); the result
 * inside it is produced by the real mapper from a wire-shaped fixture, so
 * these tests cover the path from the API body to the words on screen.
 */

import { fireEvent, render, screen } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ResultScreen } from './ResultScreen';
import { assessmentBody, classificationBody, complianceBody, extractionRunBody } from '../../tests/fixtures';
import { fakeAnalysis, PHONE_METRICS, stubNavigation } from '../../tests/render';
import { mapResult } from '../api/compliance';
import type { ComplianceCheckWire } from '../types/api';

const mockUseAnalysis = jest.fn();
jest.mock('../hooks/AnalysisContext', () => ({
  useAnalysis: () => mockUseAnalysis(),
}));

async function renderResult(body: ComplianceCheckWire | null, overrides: Parameters<typeof fakeAnalysis>[0] = {}) {
  const analysis = fakeAnalysis({
    phase: body ? 'complete' : 'idle',
    result: body ? mapResult(body) : null,
    ...overrides,
  });
  mockUseAnalysis.mockReturnValue(analysis);
  const navigation = stubNavigation();
  await render(
    <SafeAreaProvider initialMetrics={PHONE_METRICS}>
      <ResultScreen navigation={navigation as never} route={{ key: 'Result', name: 'Result' } as never} />
    </SafeAreaProvider>,
  );
  return { analysis, navigation };
}

describe('ResultScreen', () => {
  it('shows the verdict label and summary from the backend', async () => {
    await renderResult(complianceBody());

    expect(screen.getByTestId('verdict-badge')).toHaveTextContent('Partially compliant', { exact: false });
    expect(screen.getByTestId('verdict-summary')).toHaveTextContent('One requirement was not met', { exact: false });
    expect(screen.getByTestId('rule-counts')).toHaveTextContent('4 examined · 2 passed · 1 failed · 1 need review · 1 not applicable', { exact: false });
    expect(screen.getByTestId('product-type-used')).toHaveTextContent('Packaged food', { exact: false });
  });

  it.each([
    ['compliant', 'Compliant'],
    ['non_compliant', 'Non-compliant'],
    ['review_required', 'Review required'],
  ])('renders the %s verdict with the backend display label', async (result, display) => {
    await renderResult(complianceBody({ result, result_display: display }));
    expect(screen.getByTestId('verdict-badge')).toHaveTextContent(display, { exact: false });
  });

  it('renders a verdict this build has never seen without inventing a label', async () => {
    await renderResult(complianceBody({ result: 'something_new', result_display: 'Something new' }));
    expect(screen.getByTestId('verdict-badge')).toHaveTextContent('Something new', { exact: false });
  });

  it('never shows a compliance percentage', async () => {
    await renderResult(complianceBody());
    expect(screen.queryByText(/\d+% compliant/i)).toBeNull();
  });

  it('groups findings by status, failures first, and keeps not-applicable apart', async () => {
    await renderResult(complianceBody());

    expect(screen.getByTestId('findings-card')).toHaveTextContent('Requirements checked (5)', { exact: false });
    expect(screen.getByTestId('findings-group-failed')).toHaveTextContent('Failed (1)', { exact: false });
    expect(screen.getByTestId('findings-group-inconclusive')).toHaveTextContent('Needs review (1)', { exact: false });
    expect(screen.getByTestId('findings-group-passed')).toHaveTextContent('Passed (2)', { exact: false });
    expect(screen.getByTestId('findings-group-not_applicable')).toHaveTextContent('Not applicable (1)', { exact: false });

    const failed = screen.getByTestId('finding-3');
    expect(failed).toHaveTextContent('Month and year of manufacture', { exact: false });
    expect(failed).toHaveTextContent('Rule 6(1)(c)', { exact: false });
    expect(failed).toHaveTextContent('No month and year of manufacture was found on the label.', { exact: false });
    expect(failed).toHaveTextContent('“Net Qty: 500 g MRP Rs. 149.00”', { exact: false });

    const passed = screen.getByTestId('finding-1');
    expect(passed).toHaveTextContent('Reading confidence 87%', { exact: false });
    expect(passed).toHaveTextContent('not a measure of compliance', { exact: false });
  });

  it('says when the product type was chosen by the classifier rather than a person', async () => {
    await renderResult(complianceBody({ product_category_source: 'classifier' }));
    expect(screen.getByTestId('product-type-used')).toHaveTextContent('established automatically from the label', { exact: false });
  });

  it('does not describe a stated product type as automatic', async () => {
    await renderResult(complianceBody({ product_category_source: 'submitter' }));
    expect(screen.getByTestId('product-type-used')).not.toHaveTextContent('automatically', { exact: false });
  });

  it('says when the product type was not known', async () => {
    await renderResult(complianceBody({ product_category_code: null, result: 'review_required', result_display: 'Review required' }));
    expect(screen.getByTestId('product-type-used')).toHaveTextContent('Not specified', { exact: false });
  });

  it('shows the extracted fields with their confidence', async () => {
    await renderResult(complianceBody());

    expect(screen.getByTestId('extracted-net_quantity')).toHaveTextContent('Net Qty: 500 g', { exact: false });
    expect(screen.getByTestId('extracted-net_quantity')).toHaveTextContent('Reading confidence: 87%', { exact: false });
    expect(screen.getByTestId('extracted-mrp')).toHaveTextContent('MRP Rs. 149.00', { exact: false });
  });

  it('shows the classification as a suggestion with its own confidence', async () => {
    await renderResult(complianceBody({ product_category_code: null }));

    const card = screen.getByTestId('classification-card');
    expect(card).toHaveTextContent('Product classification', { exact: false });
    expect(screen.getByTestId('classification-category')).toHaveTextContent('Packaged food', { exact: false });
    expect(screen.getByTestId('classification-confidence')).toHaveTextContent('72%', { exact: false });
    expect(card).toHaveTextContent('says nothing about whether the label complies', { exact: false });
    expect(card).toHaveTextContent('not part of the compliance result', { exact: false });
  });

  it('offers to re-check with the suggested type only when no type was used, and sends it on confirmation', async () => {
    const { analysis } = await renderResult(complianceBody({ product_category_code: null }));

    await fireEvent.press(screen.getByTestId('use-classification'));

    expect(analysis.evaluate).toHaveBeenCalledWith({ categoryCode: 'packaged-food' });
  });

  it('does not offer a re-check when a product type was already used', async () => {
    await renderResult(complianceBody({ product_category_code: 'packaged-food' }));
    expect(screen.queryByTestId('use-classification')).toBeNull();
  });

  it('shows "unknown" as the classifier declining, with no re-check', async () => {
    await renderResult(
      complianceBody({
        product_category_code: null,
        extraction: extractionRunBody({ product_classification: classificationBody({ category: 'unknown', confidence: null }) }),
      }),
    );

    expect(screen.getByTestId('classification-category')).toHaveTextContent('Could not tell', { exact: false });
    expect(screen.getByTestId('classification-confidence')).toHaveTextContent('Not reported', { exact: false });
    expect(screen.queryByTestId('use-classification')).toBeNull();
  });

  it('shows what the label says behind the suggestion, with the words around it', async () => {
    await renderResult(complianceBody({ product_category_code: null }));

    const evidence = screen.getByTestId('classification-evidence');
    expect(evidence).toHaveTextContent('What the label says', { exact: false });
    expect(screen.getByTestId('signal-soap / bathing bar')).toHaveTextContent(
      '“…dove beauty bathing bar moisturising cream…”',
      { exact: false },
    );
    expect(evidence).toHaveTextContent('do not establish what this product is', { exact: false });
    expect(screen.getByTestId('classification-reason')).toHaveTextContent(
      'not accepted for automatic use',
      { exact: false },
    );
    expect(screen.getByTestId('classification-outcome')).toHaveTextContent(
      'not uploaded or read again',
      { exact: false },
    );
  });

  it('says plainly when the label offered nothing to go on', async () => {
    await renderResult(
      complianceBody({
        product_category_code: null,
        applicability_assessment: assessmentBody({
          evidence: {
            has_supporting_evidence: false,
            note: 'No text was read from this photograph, so there is no evidence from the label to support any suggestion about what kind of product this is.',
            label_signals: [],
          },
        }),
      }),
    );

    expect(screen.queryByTestId('signal-soap / bathing bar')).toBeNull();
    expect(screen.getByTestId('classification-no-evidence')).toHaveTextContent(
      'no evidence from the label',
      { exact: false },
    );
  });

  it('renders the card unchanged against a backend with no assessment', async () => {
    const { applicability_assessment: _omitted, ...older } = complianceBody({ product_category_code: null });
    await renderResult(older);

    expect(screen.getByTestId('classification-category')).toHaveTextContent('Packaged food', { exact: false });
    expect(screen.queryByTestId('classification-evidence')).toBeNull();
    expect(screen.queryByTestId('classification-reason')).toBeNull();
    expect(screen.queryByTestId('classification-outcome')).toBeNull();
  });

  it('shows no classification card when the backend made none', async () => {
    await renderResult(complianceBody({ extraction: extractionRunBody({ product_classification: null }) }));

    expect(screen.queryByTestId('classification-card')).toBeNull();
    expect(screen.getByTestId('verdict-badge')).toHaveTextContent('Partially compliant', { exact: false });

    await fireEvent.press(screen.getByTestId('toggle-technical'));
    expect(screen.getByTestId('technical-classification')).toHaveTextContent('None was made for this reading', { exact: false });
  });

  it('shows no classification card when the backend predates the field', async () => {
    const { product_classification: _omitted, ...run } = extractionRunBody();
    await renderResult(complianceBody({ extraction: run }));
    expect(screen.queryByTestId('classification-card')).toBeNull();
  });

  it('says so when no requirements were examined', async () => {
    await renderResult(complianceBody({ findings: [], rules_evaluated: 0, rules_passed: 0, rules_failed: 0, rules_inconclusive: 0 }));
    expect(screen.getByTestId('findings-empty')).toBeOnTheScreen();
  });

  it('says so when the server reports no findings at all, and lists violations instead', async () => {
    const { findings: _omitted, ...body } = complianceBody();
    await renderResult(body);

    expect(screen.getByTestId('findings-not-reported')).toBeOnTheScreen();
    expect(screen.getByTestId('findings-card')).toHaveTextContent('Violations (1)', { exact: false });
  });

  it('warns when the reading was not usable', async () => {
    await renderResult(complianceBody({ extraction: extractionRunBody({ produced_usable_output: false, status: 'empty', fields_read: [] }) }));

    expect(screen.getByTestId('unusable-reading')).toBeOnTheScreen();
    expect(screen.getByTestId('extracted-fields-empty')).toBeOnTheScreen();
  });

  it('shows a re-check error with a retry', async () => {
    const { analysis } = await renderResult(complianceBody(), {
      complianceError: Object.assign(new Error('x'), { name: 'ApiError', status: 0, code: 'network_error' }),
    });

    // A plain Error rather than an ApiError still gets a safe generic message.
    expect(screen.getByTestId('recheck-error')).toHaveTextContent('Something went wrong', { exact: false });
    await fireEvent.press(screen.getByText('Try again'));
    expect(analysis.retry).toHaveBeenCalled();
  });

  it('reveals technical details on request', async () => {
    await renderResult(complianceBody());

    expect(screen.queryByTestId('technical-card')).toBeNull();
    await fireEvent.press(screen.getByTestId('toggle-technical'));

    const card = screen.getByTestId('technical-card');
    expect(card).toHaveTextContent('tesseract 0.4.0', { exact: false });
    expect(card).toHaveTextContent('Net Qty: 500 g', { exact: false });
    expect(card).toHaveTextContent('tfidf-logreg 0.1.0', { exact: false });
  });

  it('starts over from the footer', async () => {
    const { analysis, navigation } = await renderResult(complianceBody());

    await fireEvent.press(screen.getByTestId('scan-another'));

    expect(analysis.reset).toHaveBeenCalled();
    expect(navigation.popToTop).toHaveBeenCalled();
  });

  it('handles having no result at all', async () => {
    await renderResult(null);
    expect(screen.getByText('No result to show')).toBeOnTheScreen();
  });
});
