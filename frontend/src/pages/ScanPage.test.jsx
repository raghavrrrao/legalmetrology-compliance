/**
 * The scan screen, end to end over the two-step backend flow.
 *
 * These assert what the screen must never get wrong: it uploads once and
 * evaluates the run it got back, it shows the engine's explanation alongside
 * the verdict, it presents REVIEW_REQUIRED and `inconclusive` as outcomes
 * rather than passes, and it shows what was read beside what was concluded.
 * Layout and styling are deliberately not asserted.
 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ScanPage } from './ScanPage.jsx';
import {
  complianceBody,
  extractionBody,
  extractionRunBody,
  findingBody,
} from '../test/fixtures.js';

function healthBody(overrides = {}) {
  return {
    status: 'ok',
    api_version: 'v1',
    dependencies: { database: 'ok', extraction_engine: 'ok' },
    extraction_engine: { name: 'tesseract', version: '0.2.0', is_placeholder: false },
    compliance_rules: { active_total: 3, verified: 3, unverified: 0 },
    ...overrides,
  };
}

function jsonResponse(body, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

/**
 * Route `fetch` by URL rather than by call order.
 *
 * The page makes a health request as well as the two analysis requests, and
 * the order of the first two is not something the tests should depend on.
 */
function routeFetch({ health, extraction, compliance } = {}) {
  fetch.mockImplementation(async (url) => {
    const target = String(url);
    if (target.includes('/health/')) {
      return health ?? jsonResponse(healthBody());
    }
    if (target.includes('/extraction/')) {
      return extraction ?? jsonResponse(extractionBody(), 201);
    }
    if (target.includes('/compliance/')) {
      return compliance ?? jsonResponse(complianceBody(), 201);
    }
    throw new Error(`Unexpected request to ${target}`);
  });
}

function callsTo(fragment) {
  return fetch.mock.calls.filter(([url]) => String(url).includes(fragment));
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ScanPage />
    </MemoryRouter>,
  );
}

/**
 * Choose a file and submit.
 *
 * `fireEvent` rather than `user-event`: the latter is not a dependency of this
 * project, and a file input is one of the few cases where the lower-level API
 * is equivalent - React reads `event.target.files` either way.
 */
async function uploadAndSubmit() {
  const file = new File(['fake-image-bytes'], 'label.png', { type: 'image/png' });

  fireEvent.change(screen.getByLabelText(/label photograph/i), {
    target: { files: [file] },
  });

  const submit = screen.getByRole('button', { name: /start analysis/i });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('the extraction to compliance flow', () => {
  it('disables the submit button until a file is chosen', async () => {
    routeFetch();
    renderPage();

    expect(screen.getByRole('button', { name: /start analysis/i })).toBeDisabled();
    await screen.findByText(/tesseract 0\.2\.0 is installed/i);
  });

  it('posts the file to the extraction endpoint as multipart', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    await waitFor(() => expect(callsTo('/extraction/')).toHaveLength(1));
    const [url, init] = callsTo('/extraction/')[0];
    expect(url).toContain('/api/v1/extraction/');
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.body.get('image')).toBeInstanceOf(File);
    // The browser must set the multipart boundary itself.
    expect(init.headers['Content-Type']).toBeUndefined();
  });

  it('sends the run id it was given to the compliance endpoint', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    await waitFor(() => expect(callsTo('/compliance/')).toHaveLength(1));
    const [url, init] = callsTo('/compliance/')[0];
    expect(url).toContain('/api/v1/compliance/');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      // Exactly the id the extraction response returned. Anything else would
      // mean the verdict was drawn from a different reading than the one shown.
      extraction_run_id: extractionBody().id,
    });
  });

  it('sends the category code when one was entered', async () => {
    routeFetch();
    renderPage();

    fireEvent.change(screen.getByLabelText(/product category/i), {
      target: { value: 'packaged-food' },
    });
    await uploadAndSubmit();

    await waitFor(() => expect(callsTo('/compliance/')).toHaveLength(1));
    expect(JSON.parse(callsTo('/compliance/')[0][1].body)).toEqual({
      extraction_run_id: extractionBody().id,
      category_code: 'packaged-food',
    });
  });

  it('does not re-upload the photograph to get the verdict', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    await screen.findByRole('heading', { name: /compliance assessment/i });
    // One upload, one evaluation. Re-reading the photograph could produce a
    // different reading than the one on screen.
    expect(callsTo('/extraction/')).toHaveLength(1);
    expect(callsTo('/compliance/')).toHaveLength(1);
  });

  it('makes exactly one compliance request when submitted twice quickly', async () => {
    routeFetch();
    renderPage();

    const file = new File(['bytes'], 'label.png', { type: 'image/png' });
    fireEvent.change(screen.getByLabelText(/label photograph/i), {
      target: { files: [file] },
    });
    const submit = screen.getByRole('button', { name: /start analysis/i });
    await waitFor(() => expect(submit).toBeEnabled());

    fireEvent.click(submit);
    fireEvent.click(submit);

    await screen.findByRole('heading', { name: /compliance assessment/i });
    // Each POST creates a ComplianceCheck row, so a duplicate is not merely
    // wasteful - it records an evaluation nobody asked for.
    expect(callsTo('/compliance/')).toHaveLength(1);
  });

  it('shows the pipeline stage that is running', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByLabelText(/analysis progress/i)).toBeInTheDocument();
    await screen.findByRole('heading', { name: /compliance assessment/i });
  });
});

describe('showing the result', () => {
  it('shows the verdict together with the engine’s explanation', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText('Review required')).toBeInTheDocument();
    // The summary is the sentence that says nothing was checked. A verdict
    // shown without it would imply a determination that was never made.
    expect(screen.getByText(/no compliance rules are loaded/i)).toBeInTheDocument();
  });

  it('states that review required is not a pass', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText(/this is not a pass/i)).toBeInTheDocument();
  });

  it('shows the rule counters from the result', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          rules_evaluated: 4,
          rules_passed: 2,
          rules_failed: 1,
          rules_inconclusive: 1,
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    const verdict = within(await screen.findByLabelText(/compliance verdict/i));
    expect(verdict.getByText(/2 passed/i)).toBeInTheDocument();
    expect(verdict.getByText(/1 failed/i)).toBeInTheDocument();
    expect(verdict.getByText(/1 undetermined/i)).toBeInTheDocument();
  });

  it('shows the declarations that were read, raw and normalised', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText(/net quantity/i)).toBeInTheDocument();

    // Scoped to the table: the same string also appears in the recognised-text
    // block below it, which is the point - the reading is shown beside the
    // text it came from - so an unscoped query is legitimately ambiguous.
    const table = within(screen.getByRole('table'));
    expect(table.getByText('Net Qty: 500 g')).toBeInTheDocument();
    expect(table.getByText(/"value":500/)).toBeInTheDocument();
    expect(table.getByText('91%')).toBeInTheDocument();
  });

  it('keeps extraction and compliance under separate headings', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    // A reading and a verdict are different claims. Running them together is
    // the specific thing this screen exists not to do.
    expect(
      await screen.findByRole('heading', { name: /extraction — what was read/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: /key findings — what was checked/i }),
    ).toBeInTheDocument();
  });

  it('warns when the pipeline is a placeholder that read nothing', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          extraction: extractionRunBody({
            engine_name: 'null-engine',
            is_placeholder: true,
          }),
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText(/no ocr engine is installed/i)).toBeInTheDocument();
  });

  it('keeps "named but unreadable" separate from "not found"', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          extraction: extractionRunBody({
            unread_declarations: [
              { key: 'retail_sale_price', evidence_text: 'M.R.P.', box: null, confidence: 0.4 },
            ],
          }),
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText(/named but unreadable/i)).toBeInTheDocument();
    expect(
      screen.getByText(/not a finding that the declaration is missing/i),
    ).toBeInTheDocument();
  });

  it('offers a link to the stored result', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    const link = await screen.findByRole('link', {
      name: new RegExp(complianceBody().id),
    });
    expect(link).toHaveAttribute('href', `/result/${complianceBody().id}`);
  });
});

describe('errors', () => {
  it('shows the per-field validation messages when the upload is rejected', async () => {
    routeFetch({
      extraction: jsonResponse(
        {
          error: {
            code: 'validation_error',
            message: 'The submitted data was not valid.',
            details: { image: ['Unsupported file extension.'] },
          },
        },
        400,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not be read/i);
    expect(alert).toHaveTextContent(/unsupported file extension/i);
    // Extraction failed, so no verdict was asked for.
    expect(callsTo('/compliance/')).toHaveLength(0);
  });

  it('keeps the reading when only the compliance call fails, and retries it', async () => {
    routeFetch({
      compliance: jsonResponse(
        {
          error: {
            code: 'validation_error',
            message: 'The submitted data was not valid.',
            details: { category_code: ['No active product category.'] },
          },
        },
        400,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/rules could not be checked/i);
    // The reading is unaffected and still on screen.
    expect(await screen.findByText('Net Qty: 500 g')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /check the rules again/i }));

    await waitFor(() => expect(callsTo('/compliance/')).toHaveLength(2));
    // Retrying evaluates the same run: the photograph is not uploaded again.
    expect(callsTo('/extraction/')).toHaveLength(1);
  });

  it('tells the user how to start the backend when it is unreachable', async () => {
    fetch.mockRejectedValue(new TypeError('Failed to fetch'));

    renderPage();
    await uploadAndSubmit();

    const alerts = await screen.findAllByRole('alert');
    const analysis = alerts.find((node) =>
      /could not reach the server/i.test(node.textContent),
    );
    expect(analysis).toBeDefined();
    expect(analysis).toHaveTextContent(/runserver/);
  });

  it('explains a permission error rather than showing it as a broken upload', async () => {
    routeFetch({
      extraction: jsonResponse(
        {
          error: {
            code: 'permission_denied',
            message: 'Authentication credentials were not provided.',
          },
        },
        403,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/DEMO_PUBLIC_ANALYSIS_API/);
  });
});

describe('findings', () => {
  async function renderWithFindings(findings, resultOverrides = {}) {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({ findings, rules_evaluated: findings.length, ...resultOverrides }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();
    return screen.findByRole('heading', { name: /key findings/i });
  }

  it('renders a passed finding with its requirement, evidence and confidence', async () => {
    await renderWithFindings([findingBody()]);

    expect(await screen.findByText('Net quantity declaration')).toBeInTheDocument();

    // Scoped to the finding: the same confidence appears in the extracted-data
    // table too, which is the point - the finding and the reading it was drawn
    // from are both on screen - so an unscoped query is legitimately ambiguous.
    const finding = within(screen.getByRole('article'));
    expect(finding.getByText('Passed')).toBeInTheDocument();
    expect(
      finding.getByText('The package must declare its net quantity.'),
    ).toBeInTheDocument();
    expect(finding.getByText('Rule 6(1)(e), LMPC Rules 2011')).toBeInTheDocument();
    expect(finding.getByText('91%')).toBeInTheDocument();
  });

  it('renders several findings, failures first', async () => {
    await renderWithFindings([
      findingBody({ id: 1, title: 'A passed rule', status: 'passed' }),
      findingBody({ id: 2, title: 'A failed rule', status: 'failed', violation: 7 }),
      findingBody({ id: 3, title: 'An undecided rule', status: 'inconclusive' }),
    ]);

    const titles = (await screen.findAllByRole('heading', { level: 4 })).map(
      (node) => node.textContent,
    );
    expect(titles).toEqual([
      'A failed rule',
      'An undecided rule',
      'A passed rule',
    ]);
  });

  it('never shows an inconclusive finding as a pass', async () => {
    await renderWithFindings([
      findingBody({
        status: 'inconclusive',
        message: 'The photograph could not be read.',
      }),
    ]);

    expect(await screen.findByText('Inconclusive')).toBeInTheDocument();
    expect(screen.queryByText('Passed')).not.toBeInTheDocument();
  });

  it('names the violation a failed finding became', async () => {
    await renderWithFindings([
      findingBody({ status: 'failed', violation: 42 }),
    ]);

    expect(await screen.findByText(/violation #42/i)).toBeInTheDocument();
  });

  it('explains a failure that was downgraded because the rule is unverified', async () => {
    await renderWithFindings([
      findingBody({
        status: 'inconclusive',
        downgraded_from_failed: true,
        violation: null,
      }),
    ]);

    expect(
      await screen.findByText(/recorded as undetermined, not as a violation/i),
    ).toBeInTheDocument();
  });

  it('labels severity as triage only, never as legal weight', async () => {
    await renderWithFindings([findingBody({ severity: 'critical' })]);

    expect(
      await screen.findByText(/triage ranking only, no legal weight/i),
    ).toBeInTheDocument();
  });

  it('shows an unreported confidence as unreported, never as zero', async () => {
    await renderWithFindings([findingBody({ extracted_confidence: null })]);

    expect(
      await screen.findByText(/not reported by the extraction engine/i),
    ).toBeInTheDocument();
  });

  it('survives a finding whose optional fields are all absent', async () => {
    await renderWithFindings([
      {
        id: 9,
        rule_code: 'LM-PC-0009',
        status: 'failed',
        message: 'The declaration was not found.',
      },
    ]);

    // The rule code stands in for a missing title rather than rendering blank -
    // so it legitimately appears twice, as the heading and in the meta line.
    expect(
      await screen.findByRole('heading', { level: 4, name: 'LM-PC-0009' }),
    ).toBeInTheDocument();
    expect(screen.getByText('The declaration was not found.')).toBeInTheDocument();
    expect(
      screen.getByText(/no text excerpt was recorded/i),
    ).toBeInTheDocument();
  });

  it('says no rule was examined when findings is empty', async () => {
    await renderWithFindings([]);

    // And explicitly refuses to read that as a pass. Asserted as one sentence
    // because the violations section says something similar about itself just
    // below, which is deliberate - both empty lists have to disclaim.
    expect(
      await screen.findByText(
        /no rule was examined against this reading\. that is not a finding of compliance/i,
      ),
    ).toBeInTheDocument();
  });

  it('keeps working against a backend that sends no findings key at all', async () => {
    const body = complianceBody({
      violations: [
        {
          id: 1,
          rule_code: 'DEMO-0001',
          legal_reference: 'Fixture reference',
          severity: 'major',
          field_key: 'net_quantity',
          message: 'Declaration was not found in the text read from this image.',
          evidence: [{ excerpt: 'SOME TEXT WE DID READ', bounding_box: null, note: '' }],
        },
      ],
    });
    delete body.findings;

    routeFetch({ compliance: jsonResponse(body, 201) });
    renderPage();
    await uploadAndSubmit();

    expect(
      await screen.findByText(/does not report per-rule findings/i),
    ).toBeInTheDocument();
    // Existing violation behaviour is untouched.
    expect(screen.getByText('DEMO-0001')).toBeInTheDocument();
    expect(screen.getByText('SOME TEXT WE DID READ')).toBeInTheDocument();
  });
});

describe('violations', () => {
  it('shows a violation with its rule code, reference and evidence', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          result: 'non_compliant',
          result_display: 'Non-compliant',
          rules_evaluated: 1,
          rules_failed: 1,
          findings: [findingBody({ status: 'failed', violation: 1 })],
          violations: [
            {
              id: 1,
              rule_code: 'DEMO-0001',
              legal_reference: 'Fixture reference',
              severity: 'major',
              field_key: 'net_quantity',
              message: 'Declaration was not found in the text read from this image.',
              evidence: [{ excerpt: 'SOME TEXT WE DID READ', bounding_box: null, note: '' }],
            },
          ],
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText('DEMO-0001')).toBeInTheDocument();
    expect(screen.getByText('Fixture reference')).toBeInTheDocument();
    expect(screen.getByText('SOME TEXT WE DID READ')).toBeInTheDocument();
    expect(screen.getByText('Non-compliant')).toBeInTheDocument();
  });
});

describe('unexpected data', () => {
  it('does not present an unrecognised verdict as compliant', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          result: 'quantum_superposition',
          result_display: 'Quantum superposition',
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    expect(
      await screen.findByText(/not one this build recognises/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/treat the label as needing review/i),
    ).toBeInTheDocument();
  });

  it('does not present an unrecognised finding status as a pass', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({ findings: [findingBody({ status: 'deferred' })] }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText(/unrecognised outcome/i)).toBeInTheDocument();
    expect(screen.getByText(/has not treated it as a pass/i)).toBeInTheDocument();
  });
});
