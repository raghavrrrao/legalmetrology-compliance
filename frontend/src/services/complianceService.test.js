/**
 * The mapping boundary.
 *
 * This is where the API's snake_case becomes the frontend's camelCase, and
 * these assert the cases where getting it wrong would be invisible in the UI
 * rather than obvious: an absent `findings` key read as an empty list, a null
 * confidence read as zero, an optional field read as undefined.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  evaluateExtractionRun,
  fetchComplianceResult,
} from './complianceService.js';
import { extractLabel } from './extractionService.js';
import {
  complianceBody,
  extractionBody,
  findingBody,
} from '../test/fixtures.js';

function jsonResponse(body, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('extractLabel', () => {
  it('posts multipart to the extraction endpoint and maps the run', async () => {
    fetch.mockResolvedValue(jsonResponse(extractionBody(), 201));

    const run = await extractLabel(
      new File(['bytes'], 'label.png', { type: 'image/png' }),
      { viewType: 'back' },
    );

    const [url, init] = fetch.mock.calls[0];
    expect(url).toContain('/api/v1/extraction/');
    expect(init.body.get('view_type')).toBe('back');

    expect(run.id).toBe(extractionBody().id);
    expect(run.producedUsableOutput).toBe(true);
    expect(run.isPlaceholder).toBe(false);
    expect(run.fieldsRead[0]).toEqual({
      fieldKey: 'net_quantity',
      rawValue: 'Net Qty: 500 g',
      normalizedValue: { value: 500, unit: 'g' },
      confidence: 0.91,
      boundingBox: { x: 40, y: 60, width: 200, height: 24 },
    });
    expect(run.image.width).toBe(800);
  });

  it('keeps an unreported confidence null rather than zero', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        extractionBody({
          fields_read: [
            {
              field_key: 'net_quantity',
              raw_value: '500 g',
              normalized_value: null,
              confidence: null,
              bounding_box: null,
            },
          ],
        }),
        201,
      ),
    );

    const run = await extractLabel(new File(['b'], 'l.png'));

    expect(run.fieldsRead[0].confidence).toBeNull();
    expect(run.fieldsRead[0].boundingBox).toBeNull();
  });
});

describe('evaluateExtractionRun', () => {
  it('posts the run id as JSON', async () => {
    fetch.mockResolvedValue(jsonResponse(complianceBody(), 201));

    await evaluateExtractionRun('run-1', { categoryCode: 'packaged-food' });

    const [url, init] = fetch.mock.calls[0];
    expect(url).toContain('/api/v1/compliance/');
    expect(init.method).toBe('POST');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body)).toEqual({
      extraction_run_id: 'run-1',
      category_code: 'packaged-food',
    });
  });

  it('maps a finding field for field', async () => {
    fetch.mockResolvedValue(
      jsonResponse(complianceBody({ findings: [findingBody()] }), 201),
    );

    const { findings } = await evaluateExtractionRun('run-1');

    expect(findings).toHaveLength(1);
    expect(findings[0]).toEqual({
      id: 1,
      ruleCode: 'LM-PC-0001',
      title: 'Net quantity declaration',
      requirement: 'The package must declare its net quantity.',
      legalReference: 'Rule 6(1)(e), LMPC Rules 2011',
      checkType: 'field_presence',
      severity: 'major',
      status: 'passed',
      downgradedFromFailed: false,
      fieldKey: 'net_quantity',
      extractedConfidence: 0.91,
      message: 'The declaration was found in the text read from this image.',
      evidenceExcerpt: 'Net Qty: 500 g',
      boundingBox: { x: 40, y: 60, width: 200, height: 24 },
      details: {},
      violationId: null,
    });
  });

  it('keeps a finding’s unreported confidence null, and its box null', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        complianceBody({
          findings: [
            findingBody({ extracted_confidence: null, bounding_box: null }),
          ],
        }),
        201,
      ),
    );

    const { findings } = await evaluateExtractionRun('run-1');

    expect(findings[0].extractedConfidence).toBeNull();
    expect(findings[0].boundingBox).toBeNull();
  });

  it('fills a finding’s missing optional fields without inventing values', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        complianceBody({
          findings: [
            { id: 5, rule_code: 'X-1', status: 'failed', message: 'Absent.' },
          ],
        }),
        201,
      ),
    );

    const [finding] = (await evaluateExtractionRun('run-1')).findings;

    expect(finding.title).toBe('');
    expect(finding.requirement).toBe('');
    expect(finding.details).toEqual({});
    expect(finding.downgradedFromFailed).toBe(false);
    // Absence stays absence for these two.
    expect(finding.extractedConfidence).toBeNull();
    expect(finding.violationId).toBeNull();
  });

  it('reports findings as unavailable when the key is absent', async () => {
    const body = complianceBody();
    delete body.findings;
    fetch.mockResolvedValue(jsonResponse(body, 201));

    const result = await evaluateExtractionRun('run-1');

    // The distinction the UI turns into two different sentences: "this server
    // does not report per-rule outcomes" is not "no rule was examined".
    expect(result.findingsReported).toBe(false);
    expect(result.findings).toEqual([]);
  });

  it('reports an empty findings list as reported and empty', async () => {
    fetch.mockResolvedValue(jsonResponse(complianceBody({ findings: [] }), 201));

    const result = await evaluateExtractionRun('run-1');

    expect(result.findingsReported).toBe(true);
    expect(result.findings).toEqual([]);
  });

  it('keeps violations mapped as they always were', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        complianceBody({
          violations: [
            {
              id: 3,
              rule_code: 'LM-PC-0002',
              legal_reference: 'Rule 6(1)(a)',
              severity: 'critical',
              field_key: 'manufacturer_name',
              message: 'Not declared.',
              evidence: [{ excerpt: 'READ TEXT', bounding_box: null, note: 'n' }],
            },
          ],
        }),
        201,
      ),
    );

    const { violations } = await evaluateExtractionRun('run-1');

    expect(violations[0]).toEqual({
      id: 3,
      ruleCode: 'LM-PC-0002',
      legalReference: 'Rule 6(1)(a)',
      severity: 'critical',
      fieldKey: 'manufacturer_name',
      message: 'Not declared.',
      evidence: [{ excerpt: 'READ TEXT', boundingBox: null, note: 'n' }],
    });
  });

  it('surfaces the error envelope as an ApiError', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'validation_error',
            message: 'No extraction run with that id.',
            details: { extraction_run_id: ['Not found.'] },
          },
        },
        400,
      ),
    );

    await expect(evaluateExtractionRun('nope')).rejects.toMatchObject({
      name: 'ApiError',
      status: 400,
      code: 'validation_error',
      details: { extraction_run_id: ['Not found.'] },
    });
  });
});

describe('fetchComplianceResult', () => {
  it('gets the stored result by id and maps it the same way', async () => {
    fetch.mockResolvedValue(
      jsonResponse(complianceBody({ findings: [findingBody()] })),
    );

    const result = await fetchComplianceResult(complianceBody().id);

    expect(fetch.mock.calls[0][0]).toContain(
      `/api/v1/compliance/${complianceBody().id}/`,
    );
    expect(fetch.mock.calls[0][1].method).toBe('GET');
    expect(result.findings).toHaveLength(1);
    expect(result.result).toBe('review_required');
  });
});
