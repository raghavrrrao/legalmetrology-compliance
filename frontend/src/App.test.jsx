/**
 * Application rendering.
 *
 * These assert the two things the base UI must get right: it renders without a
 * backend, and it tells the truth about what the system can currently do.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App.jsx';

function healthBody(overrides = {}) {
  return {
    status: 'ok',
    api_version: 'v1',
    dependencies: { database: 'ok', extraction_engine: 'ok' },
    extraction_engine: {
      name: 'null-engine',
      version: '0.1.0',
      is_placeholder: true,
    },
    compliance_rules: { active_total: 0, verified: 0, unverified: 0 },
    ...overrides,
  };
}

function renderApp(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <App />
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

describe('layout', () => {
  it('renders the application shell', async () => {
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => healthBody() });

    renderApp();

    // The home page's own H1. The wording changed with the interface
    // redesign - it was "Packaged commodity compliance", which named the
    // subject rather than saying what the tool does - and this assertion still
    // does the one job it ever did: prove the shell renders a heading without
    // a backend.
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: /check a package before you trust the label/i,
      }),
    ).toBeInTheDocument();
    // Wait for the health request to settle so the assertion above is not
    // followed by an unawaited state update.
    await screen.findByText(/version v1/i);
  });

  it('shows the legal disclaimer on every page', async () => {
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => healthBody() });

    renderApp();

    // `findAllBy`, because the footer now states the claim twice on purpose:
    // once in the always-visible summary line and once in the full notice
    // behind the disclosure. A single-match query would fail on the *presence*
    // of the summary, which is the opposite of what this test is for. The
    // assertion below is the stronger one - it is the full paragraph, not just
    // the phrase, that has to survive.
    const mentions = await screen.findAllByText(/not a legal determination/i);
    expect(mentions.length).toBeGreaterThan(0);
    expect(
      screen.getByText(/does not\s+certify compliance with the Legal Metrology/i),
    ).toBeInTheDocument();
    await screen.findByText(/version v1/i);
  });

  it('routes /inspections to the stored history', async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ count: 0, next: null, previous: null, results: [] }),
    });

    renderApp('/inspections');

    expect(
      await screen.findByRole('heading', { level: 1, name: /^inspections$/i }),
    ).toBeInTheDocument();
    expect(fetch.mock.calls[0][0]).toContain('/api/v1/compliance/');
  });

  it('offers the history and the scan workspace as separate navigation items', async () => {
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => healthBody() });

    renderApp();

    const nav = screen.getByRole('navigation', { name: /main/i });
    expect(
      within(nav).getByRole('link', { name: /inspections/i }),
    ).toHaveAttribute('href', '/inspections');
    expect(within(nav).getByRole('link', { name: /new scan/i })).toHaveAttribute(
      'href',
      '/scan',
    );
    await screen.findByText(/version v1/i);
  });

  it('renders a not-found page for an unknown route', async () => {
    renderApp('/no-such-page');

    expect(
      await screen.findByRole('heading', { name: /page not found/i }),
    ).toBeInTheDocument();
  });
});

describe('honesty notices', () => {
  it('states plainly that no OCR engine is installed', async () => {
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => healthBody() });

    renderApp();

    expect(
      await screen.findByText(/no ocr engine is installed/i),
    ).toBeInTheDocument();
  });

  it('states that no verified compliance rules are loaded', async () => {
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => healthBody() });

    renderApp();

    expect(
      await screen.findByText(/no verified compliance rules are loaded/i),
    ).toBeInTheDocument();
  });

  it('hides the placeholder notice once a real engine is configured', async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () =>
        healthBody({
          extraction_engine: { name: 'real', version: '1.0.0', is_placeholder: false },
        }),
    });

    renderApp();

    await screen.findByText(/real 1\.0\.0/);
    expect(screen.queryByText(/no ocr engine is installed/i)).not.toBeInTheDocument();
  });
});

describe('backend connectivity', () => {
  it('renders the health status when the backend answers', async () => {
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => healthBody() });

    renderApp();

    expect(await screen.findByText(/version v1/i)).toBeInTheDocument();
  });

  it('renders a recoverable error, not a crash, when the backend is down', async () => {
    fetch.mockRejectedValue(new TypeError('Failed to fetch'));

    renderApp();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not reach the backend/i);
    // The message must tell a new teammate what to actually do about it.
    expect(alert).toHaveTextContent(/runserver/);
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('calls the health endpoint exactly once per load', async () => {
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => healthBody() });

    renderApp();

    await waitFor(() => expect(screen.getByText(/version v1/i)).toBeInTheDocument());

    // The name of this test promises the *health* endpoint exactly once, and
    // this now asserts exactly that rather than "fetch was called once".
    //
    // The old form read `fetch.mock.calls[0][0]` and `toHaveBeenCalledTimes(1)`,
    // which only worked while health was the page's sole request. The home page
    // also loads recent inspections now, and either request can settle first -
    // so counting every call would fail for a reason that has nothing to do
    // with what this test is guarding. Filtering by URL is the stronger
    // assertion: an effect refiring on every render would still be caught, and
    // it is no longer coupled to how many *other* endpoints the page uses.
    const healthCalls = fetch.mock.calls.filter(([url]) =>
      String(url).includes('/api/v1/health/'),
    );
    expect(healthCalls).toHaveLength(1);
  });

  it('does not leave state updates pending after unmount', async () => {
    // useApiHealth aborts and guards on unmount. If it stopped doing so, React
    // would warn about setting state on an unmounted component.
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => healthBody() });
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { unmount } = renderApp();
    unmount();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(errorSpy).not.toHaveBeenCalled();
  });
});
