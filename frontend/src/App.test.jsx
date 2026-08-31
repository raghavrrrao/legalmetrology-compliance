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

    expect(
      await screen.findByRole('heading', { name: /packaged commodity compliance/i }),
    ).toBeInTheDocument();
    // Wait for the health request to settle so the assertion above is not
    // followed by an unawaited state update.
    await screen.findByText(/version v1/i);
  });

  it('shows the legal disclaimer on every page', async () => {
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => healthBody() });

    renderApp();

    expect(
      await screen.findByText(/not a legal determination/i),
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
    expect(fetch.mock.calls[0][0]).toContain('/api/v1/health/');
    // The name of this test promises "exactly once", so assert it. An effect
    // that refires on every render would be invisible otherwise.
    expect(fetch).toHaveBeenCalledTimes(1);
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
