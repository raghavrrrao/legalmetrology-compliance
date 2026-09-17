/**
 * The compliance client: the request that is sent, and how a result is mapped.
 */

import { ApiError } from './client';
import { evaluateExtractionRun, fetchComplianceResult, mapResult } from './compliance';
import { CHECK_ID, complianceBody, errorEnvelope, jsonResponse, RUN_ID } from '../../tests/fixtures';

const fetchMock = jest.fn();

beforeEach(() => {
  (globalThis as unknown as { fetch: unknown }).fetch = fetchMock;
});

describe('evaluateExtractionRun', () => {
  it('posts the run id and nothing else when no category was given', async () => {
    fetchMock.mockResolvedValue(jsonResponse(complianceBody(), { status: 201 }));

    await evaluateExtractionRun(RUN_ID);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/compliance\/$/);
    expect(JSON.parse(init.body)).toEqual({ extraction_run_id: RUN_ID });
  });

  it('sends the category code a person supplied', async () => {
    fetchMock.mockResolvedValue(jsonResponse(complianceBody(), { status: 201 }));

    await evaluateExtractionRun(RUN_ID, { categoryCode: ' packaged-food ' });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      extraction_run_id: RUN_ID,
      category_code: 'packaged-food',
    });
  });

  it('omits a blank category rather than sending an empty string', async () => {
    fetchMock.mockResolvedValue(jsonResponse(complianceBody(), { status: 201 }));

    await evaluateExtractionRun(RUN_ID, { categoryCode: '   ' });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ extraction_run_id: RUN_ID });
  });

  it('sends stated declarations when there are any', async () => {
    fetchMock.mockResolvedValue(jsonResponse(complianceBody(), { status: 201 }));

    await evaluateExtractionRun(RUN_ID, { categoryCode: 'packaged-food', declarations: { 'imported-product': 'no' } });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      extraction_run_id: RUN_ID,
      category_code: 'packaged-food',
      applicability_declarations: { 'imported-product': 'no' },
    });
  });

  it('propagates an unknown category as the backend reports it', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        errorEnvelope('validation_error', 'The submitted data was not valid.', {
          category_code: ["No active product category with code 'foood'."],
        }),
        { status: 400 },
      ),
    );

    await expect(evaluateExtractionRun(RUN_ID, { categoryCode: 'foood' })).rejects.toMatchObject({
      status: 400,
      code: 'validation_error',
    });
  });
});

describe('fetchComplianceResult', () => {
  it('gets compliance/<id>/', async () => {
    fetchMock.mockResolvedValue(jsonResponse(complianceBody()));

    const result = await fetchComplianceResult(CHECK_ID);

    expect(fetchMock.mock.calls[0][0]).toMatch(new RegExp(`/compliance/${CHECK_ID}/$`));
    expect(result.id).toBe(CHECK_ID);
  });
});

describe('mapResult', () => {
  it('maps the verdict, summary, counts and the three kinds of evidence', () => {
    const result = mapResult(complianceBody());

    expect(result).toEqual(
      expect.objectContaining({
        id: CHECK_ID,
        status: 'completed',
        result: 'partially_compliant',
        resultDisplay: 'Partially compliant',
        summary: expect.stringContaining('One requirement was not met'),
        rulesEvaluated: 4,
        rulesPassed: 2,
        rulesFailed: 1,
        rulesInconclusive: 1,
        rulesNotApplicable: 1,
        productCategoryCode: 'packaged-food',
        findingsReported: true,
      }),
    );
    expect(result.findings).toHaveLength(5);
    expect(result.findings.map((finding) => finding.status)).toEqual([
      'passed',
      'passed',
      'failed',
      'inconclusive',
      'not_applicable',
    ]);
    expect(result.violations).toHaveLength(1);
    expect(result.violations[0].evidence[0].excerpt).toContain('Net Qty');
    expect(result.extraction?.id).toBe(RUN_ID);
    expect(result.extraction?.productClassification?.category).toBe('packaged-food');
    expect(result.image?.width).toBe(1600);
  });

  it('maps a finding field for field, keeping null confidence null', () => {
    const result = mapResult(complianceBody());
    const failed = result.findings.find((finding) => finding.status === 'failed');

    expect(failed).toEqual(
      expect.objectContaining({
        id: 3,
        ruleCode: 'LMPC-MFG-DATE-001',
        clause: '6(1)(c)',
        title: 'Month and year of manufacture',
        legalReference: expect.stringContaining('Rule 6(1)(d)'),
        extractedConfidence: null,
        extractedNormalizedValue: null,
        evidenceExcerpt: 'Net Qty: 500 g MRP Rs. 149.00',
        violationId: 10,
        downgradedFromFailed: false,
      }),
    );
  });

  it('distinguishes "no findings key" from "no findings"', () => {
    const { findings: _omitted, ...withoutKey } = complianceBody();

    expect(mapResult(withoutKey).findingsReported).toBe(false);
    expect(mapResult(withoutKey).findings).toEqual([]);

    const empty = mapResult(complianceBody({ findings: [] }));
    expect(empty.findingsReported).toBe(true);
    expect(empty.findings).toEqual([]);
  });

  it('keeps an absent not-applicable count null, not zero', () => {
    const { rules_not_applicable: _omitted, ...body } = complianceBody();
    expect(mapResult(body).rulesNotApplicable).toBeNull();
  });

  it('keeps an unknown product category null', () => {
    const result = mapResult(complianceBody({ product_category_code: null, result: 'review_required' }));
    expect(result.productCategoryCode).toBeNull();
    expect(result.result).toBe('review_required');
  });

  it('carries a null classification through as null', () => {
    const result = mapResult(complianceBody({ extraction: { ...complianceBody().extraction!, product_classification: null } }));
    expect(result.extraction?.productClassification).toBeNull();
  });

  it('carries an absent classification key through as null', () => {
    const { product_classification: _omitted, ...run } = complianceBody().extraction!;
    const result = mapResult(complianceBody({ extraction: run }));
    expect(result.extraction?.productClassification).toBeNull();
  });

  it('passes an unrecognised verdict through rather than inventing one', () => {
    const result = mapResult(complianceBody({ result: 'something_new', result_display: 'Something new' }));
    expect(result.result).toBe('something_new');
    expect(result.resultDisplay).toBe('Something new');
  });

  it('rejects a body that is not a compliance result', () => {
    expect(() => mapResult(null)).toThrow(ApiError);
    expect(() => mapResult({} as never)).toThrow(ApiError);
    expect(() => mapResult({ id: CHECK_ID } as never)).toThrow(/unexpected response/i);
    expect(() => mapResult([] as never)).toThrow(ApiError);
  });

  it('tolerates a result with no extraction or image', () => {
    const result = mapResult(complianceBody({ extraction: null, image: null, violations: undefined }));
    expect(result.extraction).toBeNull();
    expect(result.image).toBeNull();
    expect(result.violations).toEqual([]);
  });
});
