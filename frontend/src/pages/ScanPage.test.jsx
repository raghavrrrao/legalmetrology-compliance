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
  applicabilityBody,
  complianceBody,
  declarationBody,
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
 * The page makes a health request and an applicability-catalogue request as
 * well as the two analysis requests, and the order of those is not something
 * the tests should depend on.
 *
 * The applicability branch must come **before** the compliance one:
 * `/api/v1/compliance/applicability-conditions/` is a compliance URL, and a
 * substring match on `/compliance/` would answer it with a verdict.
 */
function routeFetch({ health, extraction, compliance, conditions } = {}) {
  fetch.mockImplementation(async (url) => {
    const target = String(url);
    if (target.includes('/health/')) {
      return health ?? jsonResponse(healthBody());
    }
    if (target.includes('/extraction/')) {
      return extraction ?? jsonResponse(extractionBody(), 201);
    }
    if (target.includes('/applicability-conditions/')) {
      return conditions ?? jsonResponse(applicabilityBody());
    }
    if (target.includes('/compliance/')) {
      return compliance ?? jsonResponse(complianceBody(), 201);
    }
    throw new Error(`Unexpected request to ${target}`);
  });
}

/**
 * Requests to exactly one endpoint, matched on the end of the path.
 *
 * `endsWith`, not `includes`: the applicability catalogue lives under
 * `/api/v1/compliance/applicability-conditions/`, so a substring match on
 * `/compliance/` counts it as an evaluation and every assertion about how many
 * verdicts were requested becomes wrong by one.
 */
function callsTo(path) {
  return fetch.mock.calls.filter(([url]) => String(url).endsWith(path));
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

  fireEvent.change(screen.getByLabelText(/upload a product label image/i), {
    target: { files: [file] },
  });

  const submit = screen.getByRole('button', { name: /check compliance/i });
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

    expect(screen.getByRole('button', { name: /check compliance/i })).toBeDisabled();
    await screen.findByText(/tesseract 0\.2\.0/i);
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

    fireEvent.change(screen.getByLabelText(/what kind of product is this/i), {
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
    fireEvent.change(screen.getByLabelText(/upload a product label image/i), {
      target: { files: [file] },
    });
    const submit = screen.getByRole('button', { name: /check compliance/i });
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
    // The counts appear twice inside the verdict on purpose: once as the
    // sentence a reader repeats, once as the chips they check it against.
    expect(verdict.getAllByText(/2 passed/i).length).toBeGreaterThan(0);
    expect(verdict.getAllByText(/1 failed/i).length).toBeGreaterThan(0);
    expect(verdict.getAllByText(/1 requires review/i).length).toBeGreaterThan(0);
  });

  it('shows the declarations that were read, raw and normalised', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText(/net quantity/i)).toBeInTheDocument();

    // Scoped to the read-fields list: the same string also appears in the
    // recognised-text block behind the disclosure, which is the point - the
    // reading is shown beside the text it came from - so an unscoped query is
    // legitimately ambiguous.
    const read = within(screen.getByRole('list', { name: /what we read/i }));
    expect(read.getByText('Net Qty: 500 g')).toBeInTheDocument();
    expect(read.getByText(/"value":500/)).toBeInTheDocument();
    expect(read.getByText(/91%/)).toBeInTheDocument();
  });

  it('keeps extraction and compliance under separate headings', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    // A reading and a verdict are different claims. Running them together is
    // the specific thing this screen exists not to do.
    expect(
      await screen.findByRole('heading', { name: /label information/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: /requirements checked/i }),
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

    expect(await screen.findByText(/no text reader is installed/i)).toBeInTheDocument();
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
    expect(alert).toHaveTextContent(/could not read this photo/i);
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
    expect(alert).toHaveTextContent(/could not finish the check/i);
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
    return screen.findByRole('heading', { name: /requirements checked/i });
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
    expect(finding.getByText(/91%/)).toBeInTheDocument();
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

    expect(await screen.findByText('Requires review')).toBeInTheDocument();
    expect(screen.queryByText('Passed')).not.toBeInTheDocument();
  });

  it('names the violation a failed finding became', async () => {
    await renderWithFindings([
      findingBody({ status: 'failed', violation: 42 }),
    ]);

    expect(await screen.findByText(/#42/)).toBeInTheDocument();
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
      await screen.findByText(/recorded as requiring review, not as a violation/i),
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
      screen.getByText(/not detected in this photo/i),
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

describe('the four statuses are told apart', () => {
  async function renderWithFindings(findings) {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({ findings, rules_evaluated: findings.length }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();
    return screen.findByRole('heading', { name: /requirements checked/i });
  }

  it('names each status in words, not by colour alone', async () => {
    await renderWithFindings([
      findingBody({ id: 1, title: 'A passed rule', status: 'passed' }),
      findingBody({ id: 2, title: 'A failed rule', status: 'failed' }),
      findingBody({ id: 3, title: 'An undecided rule', status: 'inconclusive' }),
      findingBody({ id: 4, title: 'An excused rule', status: 'not_applicable' }),
    ]);

    // Each of the four is readable as text. A user who cannot distinguish the
    // tones - colour-blind, high-contrast mode, a printout - must still be able
    // to tell a failure from an exemption.
    expect(await screen.findByText('Passed')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Requires review')).toBeInTheDocument();
    expect(screen.getByText('Not applicable')).toBeInTheDocument();
  });

  it('never calls a not-applicable requirement a pass', async () => {
    await renderWithFindings([
      findingBody({ status: 'not_applicable', title: 'An excused rule' }),
    ]);

    expect(await screen.findByText('Not applicable')).toBeInTheDocument();
    expect(screen.queryByText('Passed')).not.toBeInTheDocument();
    expect(
      screen.getByText(/this requirement does not govern this package/i),
    ).toBeInTheDocument();
  });
});

describe('the reading does not drown the result', () => {
  it('puts the raw recognised text behind a disclosure, not on the page', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    // The fields it found come first, in the open.
    const read = within(
      await screen.findByRole('list', { name: /what we read/i }),
    );
    expect(read.getByText('Net Qty: 500 g')).toBeInTheDocument();

    // The OCR dump is still there - it is how a reviewer checks a reading that
    // looks wrong - but it is inside a closed <details>, so it cannot swamp the
    // verdict it is evidence for.
    const disclosure = screen
      .getByText(/view extracted text/i)
      .closest('details');
    expect(disclosure).not.toBeNull();
    expect(disclosure.open).toBe(false);
    expect(within(disclosure).getByText(/recognised text/i)).toBeInTheDocument();
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

/**
 * Open every collapsed question group on the page.
 *
 * The seventeen questions live in four collapsed groups now, so a test that
 * wants to reach one opens them the way a user does. Safe to call when a result
 * is on screen as well, where the form is rendered a second time under "Help us
 * finish this check".
 *
 * Waits for the groups rather than asserting them: they exist only once the
 * catalogue has been fetched and rendered, and the card's title ("Tell us
 * about this package") is on screen from the first, loading render - so a test
 * that has seen the title has not necessarily seen the groups. Which of the
 * two commits first is a scheduling question the test must not depend on; it
 * came out one way on a laptop and the other on a CI runner.
 */
async function openQuestionGroups() {
  const summaries = await waitFor(() => {
    const found = document.querySelectorAll('.question-group > summary');
    expect(found.length).toBeGreaterThan(0);
    return found;
  });
  summaries.forEach((summary) => fireEvent.click(summary));
}

/**
 * Open the question groups and answer one question.
 *
 * The first match, deliberately: the page renders the same component again
 * under "Help us finish this check" once a result exists, and a bare
 * `getByRole` would then match two groups with the same name.
 */
async function answerFirstQuestion(name, answer) {
  await openQuestionGroups();
  const [group] = screen.getAllByRole('group', { name });
  fireEvent.click(within(group).getByRole('radio', { name: answer }));
}

describe('applicability declarations', () => {
  it('offers the questions the backend served, and no others', async () => {
    routeFetch();
    renderPage();

    await screen.findByText(/tell us about this package/i);
    await openQuestionGroups();

    expect(
      screen.getByRole('group', { name: /imported product/i }),
    ).toBeInTheDocument();
  });

  it('sends nothing when no question was answered', async () => {
    routeFetch();
    renderPage();
    await screen.findByText(/tell us about this package/i);
    await openQuestionGroups();
    await uploadAndSubmit();

    await waitFor(() => expect(callsTo('/compliance/')).toHaveLength(1));
    const body = JSON.parse(callsTo('/compliance/')[0][1].body);
    // Absent, not an empty object and not a map of "unknown". Silence is the
    // honest default and the engine already treats it as unestablished.
    expect(body.applicability_declarations).toBeUndefined();
  });

  it('sends the answers that were given', async () => {
    routeFetch();
    renderPage();
    await screen.findByText(/tell us about this package/i);
    await openQuestionGroups();
    await answerFirstQuestion(/imported product/i, 'No');
    await uploadAndSubmit();

    await waitFor(() => expect(callsTo('/compliance/')).toHaveLength(1));
    const body = JSON.parse(callsTo('/compliance/')[0][1].body);
    expect(body.applicability_declarations).toEqual({ 'imported-product': 'no' });
  });

  it('sends "not sure" as unknown, never as no', async () => {
    routeFetch();
    renderPage();
    await screen.findByText(/tell us about this package/i);
    await openQuestionGroups();
    await answerFirstQuestion(/imported product/i, 'Not sure');
    await uploadAndSubmit();

    await waitFor(() => expect(callsTo('/compliance/')).toHaveLength(1));
    const body = JSON.parse(callsTo('/compliance/')[0][1].body);
    expect(body.applicability_declarations).toEqual({
      'imported-product': 'unknown',
    });
  });

  it('re-checks the same reading without uploading the photograph again', async () => {
    routeFetch();
    renderPage();
    await screen.findByText(/tell us about this package/i);
    await openQuestionGroups();
    await uploadAndSubmit();
    await screen.findByRole('button', { name: /check the rules again/i });

    await answerFirstQuestion(/imported product/i, 'No');
    fireEvent.click(
      screen.getByRole('button', { name: /check the rules again/i }),
    );

    await waitFor(() => expect(callsTo('/compliance/')).toHaveLength(2));
    // One upload, two evaluations - so the reading on screen and the new
    // verdict are provably about the same evidence.
    expect(callsTo('/extraction/')).toHaveLength(1);
    const second = JSON.parse(callsTo('/compliance/')[1][1].body);
    expect(second.extraction_run_id).toBe(extractionBody().id);
    expect(second.applicability_declarations).toEqual({
      'imported-product': 'no',
    });
  });

  it('still analyses a label when the catalogue could not be loaded', async () => {
    routeFetch({ conditions: jsonResponse({ error: { message: 'nope' } }, 500) });
    renderPage();
    await uploadAndSubmit();

    await waitFor(() => expect(callsTo('/compliance/')).toHaveLength(1));
    expect(
      await screen.findByText(/could not be loaded/i),
    ).toBeInTheDocument();
  });

  it('shows what was declared, apart from what was read', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          applicability_declarations: [
            declarationBody({ answer: 'yes', answer_display: 'Yes' }),
          ],
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    const heading = await screen.findByRole('heading', {
      name: /what you told us about this package/i,
    });
    expect(heading).toBeInTheDocument();
    // Labelled as an assertion, never as a measurement.
    expect(screen.getByText(/stated by a person/i)).toBeInTheDocument();
    expect(screen.getByText(/nothing here was verified/i)).toBeInTheDocument();
  });

  it('says so when nothing was declared', async () => {
    routeFetch();
    renderPage();
    await uploadAndSubmit();

    expect(
      await screen.findByText(/no fact was stated about this package/i),
    ).toBeInTheDocument();
  });

  it('flags a declaration recorded after the check ran', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          applicability_declarations: [
            declarationBody({ stated_before_this_check: false }),
          ],
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    expect(
      await screen.findByText(/did not affect this result/i),
    ).toBeInTheDocument();
  });
});

describe('not applicable', () => {
  it('is shown as its own outcome and never as a pass', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          rules_not_applicable: 1,
          findings: [
            findingBody({
              status: 'not_applicable',
              message:
                'Clause 6(1)(aa) applies only to: Imported product. None was declared for this package.',
            }),
          ],
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    expect(
      await screen.findByText(/does not govern this package/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/so this is not a pass/i)).toBeInTheDocument();
    // And it is not silently counted among the passes.
    expect(screen.getByText(/1 did not apply/i)).toBeInTheDocument();
    expect(screen.getByText(/are not passes/i)).toBeInTheDocument();
  });
});

describe('why a review is required', () => {
  it('names the fact the engine could not establish', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          result: 'review_required',
          findings: [
            findingBody({
              status: 'inconclusive',
              details: { unresolved_conditions: ['bidi'] },
            }),
          ],
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText(/why can.t we decide/i)).toBeInTheDocument();
    expect(screen.getByText(/was not stated/i)).toBeInTheDocument();
  });

  it('says a photograph cannot settle a physical requirement', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          findings: [
            findingBody({
              status: 'inconclusive',
              detection_method: 'physical_inspection',
              details: {},
            }),
          ],
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    expect(
      await screen.findByText(/a photo cannot settle this/i),
    ).toBeInTheDocument();
  });

  it('invents no reason when the response gives none', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          findings: [findingBody({ status: 'inconclusive', details: {} })],
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    await screen.findByText('Requires review');
    expect(
      screen.queryByText(/why can.t we decide/i),
    ).not.toBeInTheDocument();
  });
});

describe('legal context and evidence', () => {
  it('shows the clause, the source and the extracted value it was read from', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({ findings: [findingBody()] }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    await screen.findByText(/text read from the photo/i);
    expect(screen.getByText(/Rule 6\(1\)\(c\)/)).toBeInTheDocument();
    expect(screen.getByText(/G\.S\.R\. 202\(E\)/)).toBeInTheDocument();
    expect(
      screen.getByText(/the notification that last\s+amended this clause/i),
    ).toBeInTheDocument();
  });

  it('says when no amending notification is recorded, rather than showing a gap', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          findings: [findingBody({ legal_source_citation: '' })],
        }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    expect(
      await screen.findByText(/no amending notification is recorded/i),
    ).toBeInTheDocument();
  });

  it('offers the applicability note without putting it in the user’s way', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({ findings: [findingBody()] }),
        201,
      ),
    });
    renderPage();
    await uploadAndSubmit();

    const disclosure = await screen.findByText(
      /why this requirement was applied/i,
    );
    fireEvent.click(disclosure);
    expect(
      screen.getByText(/carries no applicability conditions/i),
    ).toBeInTheDocument();
  });
});

describe('no compliance score', () => {
  it('shows no percentage or score anywhere on the result', async () => {
    routeFetch({
      compliance: jsonResponse(
        complianceBody({
          result: 'compliant',
          result_display: 'Compliant',
          rules_evaluated: 4,
          rules_passed: 4,
          findings: [findingBody()],
        }),
        201,
      ),
    });
    const { container } = renderPage();
    await uploadAndSubmit();

    await screen.findByText(/compliant/i);
    expect(screen.queryByText(/compliance score/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\b\d{1,3}\s*\/\s*100\b/)).not.toBeInTheDocument();
    // The one percentage the screen may show is the OCR engine's own reported
    // confidence in a reading, which is labelled as such and affects nothing.
    // Asserted non-empty first, so this cannot pass by there being no numbers
    // on the page at all.
    const percentages = container.textContent.match(/\d+%/g) ?? [];
    expect(percentages.length).toBeGreaterThan(0);
    expect(new Set(percentages)).toEqual(new Set(['91%']));
    expect(screen.getAllByText(/reading confidence/i).length).toBeGreaterThan(0);
  });
});
