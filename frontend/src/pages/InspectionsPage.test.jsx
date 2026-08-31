/**
 * The Inspections screen, over the real history endpoint.
 *
 * These assert what the screen must not get wrong: it draws what the API
 * returned and nothing else, it reaches the stored result by the row's own id,
 * it walks pages by the URLs the backend built rather than by numbers of its
 * own, and it tells an empty history apart from a failed request. Layout and
 * styling are deliberately not asserted.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { InspectionsPage } from './InspectionsPage.jsx';
import { ResultPage } from './ResultPage.jsx';
import {
  complianceBody,
  historyBody,
  historyRowBody,
} from '../test/fixtures.js';

const PAGE_TWO_URL = 'http://localhost:8000/api/v1/compliance/?page=2';
const PAGE_ONE_URL = 'http://localhost:8000/api/v1/compliance/?page=1';

function jsonResponse(body, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

/** True for `/compliance/<uuid>/`, false for the collection and its pages. */
function isDetailRequest(url) {
  return /\/compliance\/[0-9a-f-]{36}\/?$/i.test(String(url).split('?')[0]);
}

function historyCalls() {
  return fetch.mock.calls.filter(
    ([url]) => String(url).includes('/compliance/') && !isDetailRequest(url),
  );
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/inspections']}>
      <Routes>
        <Route path="/inspections" element={<InspectionsPage />} />
        <Route path="/result/:checkId" element={<ResultPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('loading the history', () => {
  it('shows a loading state while the first page is fetched', async () => {
    fetch.mockResolvedValue(jsonResponse(historyBody()));

    renderPage();

    expect(screen.getByRole('status')).toHaveTextContent(
      /loading stored inspections/i,
    );
    await screen.findByRole('link', { name: /result 11111111/i });
  });

  it('requests the collection endpoint once and lists what it returned', async () => {
    fetch.mockResolvedValue(jsonResponse(historyBody()));

    renderPage();

    await screen.findByRole('link', { name: /result 11111111/i });
    expect(historyCalls()).toHaveLength(1);
    expect(String(historyCalls()[0][0])).toContain('/api/v1/compliance/');
  });

  it('shows the verdict, the time, the category and both counts for a row', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        historyBody({
          results: [historyRowBody({ product_category_code: 'FOOD' })],
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText('Review required')).toBeInTheDocument();
    expect(screen.getByText('FOOD')).toBeInTheDocument();
    expect(screen.getByText('v0.1.0')).toBeInTheDocument();
    expect(screen.getByText(/4 rules examined/)).toBeInTheDocument();
    expect(screen.getByText(/2 violations/)).toBeInTheDocument();
    // The machine-readable timestamp is the API's own value, whatever the
    // reader's locale renders beside it.
    expect(
      document.querySelector('time[datetime="2026-08-30T12:00:00Z"]'),
    ).toBeInTheDocument();
  });

  it('reports the endpoint total rather than the number of rows on the page', async () => {
    fetch.mockResolvedValue(
      jsonResponse(historyBody({ count: 42, next: PAGE_TWO_URL })),
    );

    renderPage();

    expect(
      await screen.findByRole('heading', { name: /stored assessments \(42\)/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/showing 1 of 42 stored assessments/i),
    ).toBeInTheDocument();
  });

  it('claims no total when the response carried no count', async () => {
    const body = historyBody();
    delete body.count;
    fetch.mockResolvedValue(jsonResponse(body));

    renderPage();

    await screen.findByRole('link', { name: /result 11111111/i });
    expect(
      screen.getByRole('heading', { name: /^stored assessments$/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/showing 1 of the stored assessments/i),
    ).toBeInTheDocument();
  });
});

describe('navigating to a stored result', () => {
  it('links each row to /result/<uuid>', async () => {
    fetch.mockResolvedValue(jsonResponse(historyBody()));

    renderPage();

    const link = await screen.findByRole('link', { name: /result 11111111/i });
    expect(link).toHaveAttribute('href', `/result/${historyRowBody().id}`);
  });

  it('opens the stored result when a row is clicked', async () => {
    fetch.mockImplementation(async (url) => {
      if (isDetailRequest(url)) {
        return jsonResponse(complianceBody());
      }
      return jsonResponse(historyBody());
    });

    renderPage();

    fireEvent.click(await screen.findByRole('link', { name: /result 11111111/i }));

    expect(
      await screen.findByRole('heading', { name: /compliance assessment/i }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([url]) =>
          String(url).endsWith(`/compliance/${historyRowBody().id}/`),
        ),
      ).toBe(true),
    );
  });
});

describe('empty and failed states', () => {
  it('says nothing has been assessed rather than showing an error', async () => {
    fetch.mockResolvedValue(
      jsonResponse({ count: 0, next: null, previous: null, results: [] }),
    );

    renderPage();

    expect(
      await screen.findByText(/nothing has been assessed yet/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /next page/i }),
    ).not.toBeInTheDocument();
  });

  it('renders the API error envelope and recovers when retried', async () => {
    fetch.mockResolvedValueOnce(
      jsonResponse(
        { error: { code: 'not_found', message: 'Invalid page.' } },
        404,
      ),
    );
    fetch.mockResolvedValue(jsonResponse(historyBody()));

    renderPage();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/inspection history could not be loaded/i);
    expect(alert).toHaveTextContent(/invalid page/i);

    fireEvent.click(screen.getByRole('button', { name: /try again/i }));

    expect(
      await screen.findByRole('link', { name: /result 11111111/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('tells the user to start the backend when the request never arrives', async () => {
    fetch.mockRejectedValue(new TypeError('Failed to fetch'));

    renderPage();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not reach the server/i);
    expect(alert).toHaveTextContent(/runserver/);
  });
});

describe('pagination', () => {
  function routePages() {
    fetch.mockImplementation(async (url) => {
      const target = String(url);
      if (target.includes('page=2')) {
        return jsonResponse(
          historyBody({
            count: 2,
            next: null,
            previous: PAGE_ONE_URL,
            results: [
              historyRowBody({
                id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                result: 'non_compliant',
                result_display: 'Non-compliant',
              }),
            ],
          }),
        );
      }
      return jsonResponse(
        historyBody({ count: 2, next: PAGE_TWO_URL, previous: null }),
      );
    });
  }

  it('follows the API next URL rather than building a page number', async () => {
    routePages();

    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /next page/i }));

    expect(
      await screen.findByRole('link', { name: /result aaaaaaaa/i }),
    ).toBeInTheDocument();
    expect(String(historyCalls()[1][0])).toBe(PAGE_TWO_URL);
  });

  it('follows the API previous URL back', async () => {
    routePages();

    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /next page/i }));
    await screen.findByRole('link', { name: /result aaaaaaaa/i });

    fireEvent.click(screen.getByRole('button', { name: /previous page/i }));

    expect(
      await screen.findByRole('link', { name: /result 11111111/i }),
    ).toBeInTheDocument();
    expect(String(historyCalls()[2][0])).toBe(PAGE_ONE_URL);
  });

  it('disables next when the API reports no next page', async () => {
    fetch.mockResolvedValue(jsonResponse(historyBody({ next: null })));

    renderPage();

    await screen.findByRole('link', { name: /result 11111111/i });
    expect(screen.getByRole('button', { name: /next page/i })).toBeDisabled();
  });

  it('disables previous when the API reports no previous page', async () => {
    fetch.mockResolvedValue(
      jsonResponse(historyBody({ previous: null, next: PAGE_TWO_URL })),
    );

    renderPage();

    await screen.findByRole('link', { name: /result 11111111/i });
    expect(screen.getByRole('button', { name: /previous page/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /next page/i })).toBeEnabled();
  });
});

describe('rows the API sent incompletely', () => {
  it('renders a row with missing fields without crashing the page', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        historyBody({
          results: [
            // Everything the list serializer declares, absent. A response like
            // this should not be possible; a screen that white-screened on one
            // would take the whole history down with it.
            { id: undefined, created_at: 'not-a-date' },
            historyRowBody(),
          ],
        }),
      ),
    );

    renderPage();

    expect(
      await screen.findByRole('link', { name: /result 11111111/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/no identifier returned/i)).toBeInTheDocument();
    expect(screen.getByText(/not recorded/i)).toBeInTheDocument();
  });

  it('shows no count rather than zero when a count was not reported', async () => {
    const row = historyRowBody();
    delete row.findings_count;
    delete row.violations_count;
    fetch.mockResolvedValue(jsonResponse(historyBody({ results: [row] })));

    renderPage();

    await screen.findByRole('link', { name: /result 11111111/i });
    expect(screen.queryByText(/rules examined/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 violations/)).not.toBeInTheDocument();
  });

  it('does not show a verdict for an evaluation that did not complete', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        historyBody({ results: [historyRowBody({ status: 'failed' })] }),
      ),
    );

    renderPage();

    expect(await screen.findByText('Failed')).toBeInTheDocument();
    expect(screen.queryByText('Review required')).not.toBeInTheDocument();
    expect(screen.getByText(/no verdict is shown for it/i)).toBeInTheDocument();
  });

  it('marks a verdict this build does not recognise as uninterpreted', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        historyBody({
          results: [
            historyRowBody({
              result: 'provisionally_exempt',
              result_display: 'Provisionally exempt',
            }),
          ],
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText('Provisionally exempt')).toBeInTheDocument();
    expect(screen.getByText(/not one this build recognises/i)).toBeInTheDocument();
  });
});
