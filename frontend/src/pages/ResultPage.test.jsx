/**
 * The permalink screen.
 *
 * `GET /api/v1/compliance/<uuid>/` exists so a result can be reopened and sent
 * to a reviewer. These assert that the link actually resolves to the same
 * screen, and that the one thing it cannot show - the photograph - is reported
 * honestly rather than as a broken image.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { ResultPage } from './ResultPage.jsx';
import { complianceBody, findingBody } from '../test/fixtures.js';

function jsonResponse(body, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

function renderPage(checkId = complianceBody().id) {
  return render(
    <MemoryRouter initialEntries={[`/result/${checkId}`]}>
      <Routes>
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

it('shows a loading state while the result is fetched', async () => {
  fetch.mockResolvedValue(jsonResponse(complianceBody()));

  renderPage();

  expect(screen.getByRole('status')).toHaveTextContent(/loading the stored result/i);
  await screen.findByText('Review required');
});

it('loads the stored result by id and renders its findings', async () => {
  fetch.mockResolvedValue(
    jsonResponse(complianceBody({ findings: [findingBody()] })),
  );

  renderPage();

  expect(await screen.findByText('Net quantity declaration')).toBeInTheDocument();
  expect(screen.getByText('Review required')).toBeInTheDocument();
  expect(fetch.mock.calls[0][0]).toContain(
    `/api/v1/compliance/${complianceBody().id}/`,
  );
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
});

it('says the photograph is unavailable rather than showing a broken image', async () => {
  fetch.mockResolvedValue(jsonResponse(complianceBody()));

  renderPage();

  expect(
    await screen.findByText(/not available on this device/i),
  ).toBeInTheDocument();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});

it('explains a 404 rather than rendering an empty screen', async () => {
  fetch.mockResolvedValue(
    jsonResponse(
      { error: { code: 'not_found', message: 'No ComplianceCheck matches the given query.' } },
      404,
    ),
  );

  renderPage('00000000-0000-0000-0000-000000000000');

  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent(/could not be loaded/i);
  expect(alert).toHaveTextContent(/no result exists with this id/i);
});

it('offers a retry when the backend is unreachable', async () => {
  fetch.mockRejectedValue(new TypeError('Failed to fetch'));

  renderPage();

  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent(/runserver/);
  expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
});
