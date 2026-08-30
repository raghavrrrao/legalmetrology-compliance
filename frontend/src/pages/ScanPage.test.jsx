/**
 * The scan screen.
 *
 * These assert what the screen must never get wrong: it shows the engine's
 * explanation alongside the verdict, it presents REVIEW_REQUIRED as an outcome
 * rather than a pass, and it shows what was read beside what was concluded.
 * Layout and styling are deliberately not asserted.
 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ScanPage } from './ScanPage.jsx';

function resultBody(overrides = {}) {
  return {
    id: '11111111-2222-3333-4444-555555555555',
    status: 'completed',
    result: 'review_required',
    result_display: 'Review required',
    summary:
      'No compliance rules are loaded for this product’s category, so nothing was checked.',
    engine_version: '0.1.0',
    rules_evaluated: 0,
    rules_passed: 0,
    rules_failed: 0,
    rules_inconclusive: 0,
    processing_ms: 1200,
    completed_at: '2026-08-30T12:00:00Z',
    product_category_code: null,
    violations: [],
    extraction: {
      id: '99999999-8888-7777-6666-555555555555',
      engine_name: 'tesseract',
      engine_version: '0.2.0',
      is_placeholder: false,
      status: 'completed',
      produced_usable_output: true,
      processing_ms: 1100,
      recognised_text: 'Net Qty: 500 g',
      error_code: '',
      error_message: '',
      fields_read: [
        {
          field_key: 'net_quantity',
          raw_value: 'Net Qty: 500 g',
          normalized_value: { value: 500, unit: 'g' },
          confidence: 0.91,
          bounding_box: null,
        },
      ],
      unread_declarations: [],
    },
    image: {
      id: '77777777-6666-5555-4444-333333333333',
      original_filename: 'label.png',
      image_format: 'png',
      width: 800,
      height: 600,
      size_bytes: 12345,
      view_type: 'back',
      status: 'processed',
    },
    ...overrides,
  };
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

  const submit = screen.getByRole('button', { name: /analyse label/i });
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

describe('submitting a label', () => {
  it('disables the submit button until a file is chosen', () => {
    renderPage();

    expect(screen.getByRole('button', { name: /analyse label/i })).toBeDisabled();
  });

  it('posts the file to the images endpoint as multipart', async () => {
    fetch.mockResolvedValue({ ok: true, status: 201, json: async () => resultBody() });

    renderPage();
    await uploadAndSubmit();

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    const [url, init] = fetch.mock.calls[0];
    expect(url).toContain('/api/v1/images/');
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.body.get('image')).toBeInstanceOf(File);
    // The browser must set the multipart boundary itself.
    expect(init.headers['Content-Type']).toBeUndefined();
  });
});

describe('showing the result', () => {
  it('shows the verdict together with the engine’s explanation', async () => {
    fetch.mockResolvedValue({ ok: true, status: 201, json: async () => resultBody() });

    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText(/review required/i)).toBeInTheDocument();
    // The summary is the sentence that says nothing was checked. A verdict
    // shown without it would imply a determination that was never made.
    expect(screen.getByText(/no compliance rules are loaded/i)).toBeInTheDocument();
  });

  it('states that review required is not a pass', async () => {
    fetch.mockResolvedValue({ ok: true, status: 201, json: async () => resultBody() });

    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText(/this is not a pass/i)).toBeInTheDocument();
  });

  it('shows the declarations that were read, raw and normalised', async () => {
    fetch.mockResolvedValue({ ok: true, status: 201, json: async () => resultBody() });

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

  it('shows a finding with its rule code, reference and evidence', async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 201,
      json: async () =>
        resultBody({
          result: 'non_compliant',
          result_display: 'Non-compliant',
          rules_evaluated: 1,
          rules_failed: 1,
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
    });

    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText('DEMO-0001')).toBeInTheDocument();
    expect(screen.getByText(/fixture reference/i)).toBeInTheDocument();
    expect(screen.getByText('SOME TEXT WE DID READ')).toBeInTheDocument();
  });

  it('warns when the pipeline is a placeholder that read nothing', async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 201,
      json: async () =>
        resultBody({
          extraction: {
            ...resultBody().extraction,
            engine_name: 'null-engine',
            is_placeholder: true,
          },
        }),
    });

    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText(/no ocr engine is installed/i)).toBeInTheDocument();
  });

  it('keeps "named but unreadable" separate from "not found"', async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 201,
      json: async () =>
        resultBody({
          extraction: {
            ...resultBody().extraction,
            unread_declarations: [
              { key: 'retail_sale_price', evidence_text: 'M.R.P.', box: null, confidence: 0.4 },
            ],
          },
        }),
    });

    renderPage();
    await uploadAndSubmit();

    expect(await screen.findByText(/named but unreadable/i)).toBeInTheDocument();
    expect(
      screen.getByText(/not a finding that the declaration is missing/i),
    ).toBeInTheDocument();
  });
});

describe('errors', () => {
  it('shows the per-field validation messages from the error envelope', async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({
        error: {
          code: 'validation_error',
          message: 'The submitted data was not valid.',
          details: { image: ['Unsupported file extension.'] },
        },
      }),
    });

    renderPage();
    await uploadAndSubmit();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/unsupported file extension/i);
  });

  it('tells the user how to start the backend when it is unreachable', async () => {
    fetch.mockRejectedValue(new TypeError('Failed to fetch'));

    renderPage();
    await uploadAndSubmit();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not reach the server/i);
    expect(alert).toHaveTextContent(/runserver/);
  });
});
