/**
 * The Rules screen lists what the server reports, and claims nothing else.
 *
 * Only `fetch` is replaced. The hook, the API module, its mapping and its
 * validation all run as they do in the app, so "the server's rules are shown"
 * here means a wire-shaped response went through the real client and came out
 * on screen - not that a prop was rendered.
 *
 * The assertions are about honesty more than layout: nothing is shown before
 * the server answers, the bundled repository mirror is never shown at all, an
 * inactive rule is listed and marked rather than hidden, a failure says the
 * list was not loaded, and the screen computes nothing about any package.
 */

import { fireEvent, render, screen, within } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { RulesScreen } from './RulesScreen';
import {
  errorEnvelope,
  jsonResponse,
  ruleBody,
  ruleInventoryBody,
  rulesPageBody,
} from '../../tests/fixtures';
import { PHONE_METRICS } from '../../tests/render';
import { config, describeApiTarget } from '../config/env';

// The repository mirror must never reach this screen - not as a placeholder
// while loading, not as a fallback on failure, not merged into the server's
// list. Loading the module at all fails the file.
jest.mock('../data/lmpcRules', () => {
  throw new Error('The Rules screen must not load the bundled rule mirror.');
});

const fetchMock = jest.fn();
const host = describeApiTarget(config.apiBaseUrl).host;

beforeEach(() => {
  (globalThis as unknown as { fetch: unknown }).fetch = fetchMock;
});

async function renderRules() {
  await render(
    <SafeAreaProvider initialMetrics={PHONE_METRICS}>
      <RulesScreen />
    </SafeAreaProvider>,
  );
}

function serveRules(rules: unknown[] = ruleInventoryBody()) {
  fetchMock.mockResolvedValue(jsonResponse(rulesPageBody(rules)));
}

/**
 * Answer the next request only when the test says so, to hold the screen in
 * loading. Aborting it rejects it, as a real fetch does, so a screen unmounted
 * mid-request leaves no timer behind.
 */
function holdNextResponse() {
  let release: ((value: Response) => void) | null = null;
  fetchMock.mockImplementationOnce(
    (_url: string, init: RequestInit) =>
      new Promise<Response>((resolve, reject) => {
        release = resolve;
        init.signal?.addEventListener('abort', () =>
          reject(Object.assign(new Error('aborted'), { name: 'AbortError' })),
        );
      }),
  );
  return {
    release(value: Response) {
      if (!release) {
        throw new Error('holdNextResponse: the request was never made');
      }
      release(value);
    },
  };
}

function renderedCodes(): string[] {
  return screen
    .getAllByTestId(/^rule-LM-/)
    .map((row) => String(row.props.testID).replace(/^rule-/, ''));
}

describe('while the server has not answered', () => {
  it('says it is loading, and shows no counts, no list and no other rules', async () => {
    holdNextResponse();

    await renderRules();

    expect(screen.getByTestId('rules-loading')).toHaveTextContent(`Loading the rule list from ${host}`, {
      exact: false,
    });
    expect(screen.queryByTestId('rule-counts-summary')).toBeNull();
    expect(screen.queryByTestId('rules-list')).toBeNull();
    expect(screen.queryAllByTestId(/^rule-LM-/)).toHaveLength(0);
    // A title the bundled mirror carries: nothing stands in for the server's list.
    expect(screen.queryByText('Net quantity of the commodity')).toBeNull();
  });
});

describe('with the server’s rule inventory', () => {
  it('lists every rule the server returned, with code, clause, title and reference', async () => {
    serveRules();

    await renderRules();
    await screen.findByTestId('rules-list');

    for (const rule of ruleInventoryBody()) {
      const row = screen.getByTestId(`rule-${rule.code}`);
      expect(row).toHaveTextContent(rule.code, { exact: false });
      expect(row).toHaveTextContent(`Rule ${rule.clause}`, { exact: false });
      expect(row).toHaveTextContent(rule.title, { exact: false });
      expect(within(row).getByTestId(`rule-reference-${rule.code}`)).toHaveTextContent(
        rule.legal_reference,
      );
    }
    expect(screen.queryByTestId('rules-loading')).toBeNull();
  });

  it('shows the server’s count, and the active and inactive tallies of its flags', async () => {
    serveRules();

    await renderRules();
    const summary = await screen.findByTestId('rule-counts-summary');

    expect(summary).toHaveTextContent(/4\s*TOTAL/);
    expect(summary).toHaveTextContent(/3\s*ACTIVE/);
    expect(summary).toHaveTextContent(/1\s*INACTIVE/);
  });

  it('follows the counts wherever the server’s inventory goes - nothing is fixed at twelve', async () => {
    const rules = [
      ruleBody({ code: 'LM-PC-0001' }),
      ruleBody({ code: 'LM-PC-0002', is_active: false }),
      ruleBody({ code: 'LM-PC-0003', is_active: false }),
    ];
    serveRules(rules);

    await renderRules();
    const summary = await screen.findByTestId('rule-counts-summary');

    expect(summary).toHaveTextContent(/3\s*TOTAL/);
    expect(summary).toHaveTextContent(/1\s*ACTIVE/);
    expect(summary).toHaveTextContent(/2\s*INACTIVE/);
  });

  it('marks an inactive rule as not evaluated rather than hiding it', async () => {
    serveRules();

    await renderRules();
    await screen.findByTestId('rules-list');

    expect(screen.getByTestId('rule-LM-PC-0002')).toBeOnTheScreen();
    expect(screen.getByTestId('rule-inactive-LM-PC-0002')).toHaveTextContent('Not evaluated');
    for (const code of ['LM-PC-0001', 'LM-PC-0003', 'LM-PC-0008']) {
      expect(screen.queryByTestId(`rule-inactive-${code}`)).toBeNull();
    }
  });

  it('marks a rule the server reports as unverified, and only that one', async () => {
    serveRules([ruleBody({ code: 'LM-PC-0001' }), ruleBody({ code: 'LM-PC-0002', source_status: 'unverified' })]);

    await renderRules();
    await screen.findByTestId('rules-list');

    expect(screen.getByTestId('rule-unverified-LM-PC-0002')).toHaveTextContent('Not yet verified');
    expect(screen.queryByTestId('rule-unverified-LM-PC-0001')).toBeNull();
  });

  it('keeps the server’s order', async () => {
    serveRules([ruleBody({ code: 'LM-PC-0012' }), ruleBody({ code: 'LM-PC-0001' }), ruleBody({ code: 'LM-PC-0007' })]);

    await renderRules();
    await screen.findByTestId('rules-list');

    expect(renderedCodes()).toEqual(['LM-PC-0012', 'LM-PC-0001', 'LM-PC-0007']);
  });

  it('shows the server’s data, not the bundled copy’s', async () => {
    // Same code as a bundled rule, different words, and a code the bundle does
    // not have. Only what the server sent may appear.
    serveRules([
      ruleBody({ code: 'LM-PC-0003', title: 'Net quantity, as this server words it' }),
      ruleBody({ code: 'LM-PC-0099', title: 'A rule only this server has', clause: '99(1)' }),
    ]);

    await renderRules();
    await screen.findByTestId('rules-list');

    expect(renderedCodes()).toEqual(['LM-PC-0003', 'LM-PC-0099']);
    expect(screen.getByText('Net quantity, as this server words it')).toBeOnTheScreen();
    expect(screen.getByText('A rule only this server has')).toBeOnTheScreen();
    expect(screen.queryByText('Net quantity of the commodity')).toBeNull();
    expect(screen.queryByTestId('rule-LM-PC-0001')).toBeNull();
    expect(screen.getByTestId('rule-counts-summary')).toHaveTextContent(/2\s*TOTAL/);
  });

  it('shows no clause when the server links none, and never reads one out of the reference', async () => {
    serveRules([
      ruleBody({
        code: 'LM-PC-0001',
        clause: null,
        legal_reference: 'Rule 6(1)(c) of the Legal Metrology (Packaged Commodities) Rules, 2011',
      }),
    ]);

    await renderRules();
    const row = await screen.findByTestId('rule-LM-PC-0001');

    // The reference is shown verbatim; no "Rule 6(1)(c)" label is composed from it.
    expect(within(row).getByTestId('rule-reference-LM-PC-0001')).toBeOnTheScreen();
    expect(within(row).queryByText('Rule 6(1)(c)')).toBeNull();
  });

  it('says where the list came from, and that it is the server’s', async () => {
    serveRules();

    await renderRules();

    expect(await screen.findByTestId('rules-source')).toHaveTextContent(
      `Reported by the compliance server at ${host}.`,
    );
    expect(screen.getByText(/as the server reports them/)).toBeOnTheScreen();
    // The old wording described the bundled copy; it must not survive.
    expect(screen.queryByText(/this version of the app was built with/i)).toBeNull();
  });

  it('asks the server for the rule inventory and nothing else', async () => {
    serveRules();

    await renderRules();
    await screen.findByTestId('rules-list');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/rules\/\?page_size=\d+$/);
    expect(init.method).toBe('GET');
    // No inspection history, no stored result, no upload, no evaluation.
    expect(url).not.toMatch(/compliance|images|extraction/);
  });
});

describe('nothing is computed about any package', () => {
  it('shows the server’s active flag as sent, whatever the dates or verification say', async () => {
    serveRules([
      // Closed window, but the server says active: listed as active.
      ruleBody({ code: 'LM-PC-0001', effective_from: '2011-04-01', effective_to: '2012-01-01', is_active: true }),
      // Not yet in force, but active on the server: listed as active.
      ruleBody({ code: 'LM-PC-0002', effective_from: '2099-01-01', is_active: true }),
      // In force and verified, but inactive on the server: listed as inactive.
      ruleBody({ code: 'LM-PC-0003', effective_from: '2011-04-01', is_active: false }),
    ]);

    await renderRules();
    await screen.findByTestId('rules-list');

    expect(screen.queryByTestId('rule-inactive-LM-PC-0001')).toBeNull();
    expect(screen.queryByTestId('rule-inactive-LM-PC-0002')).toBeNull();
    expect(screen.getByTestId('rule-inactive-LM-PC-0003')).toBeOnTheScreen();
    expect(screen.getByTestId('rule-counts-summary')).toHaveTextContent(/2\s*ACTIVE/);
  });

  it('shows nothing a server might send beyond the contract', async () => {
    serveRules([
      {
        ...ruleBody({ code: 'LM-PC-0001' }),
        check_type: 'field_presence',
        parameters: { field_key: 'net_quantity' },
        source_note: 'Verified by a named reviewer.',
      },
    ]);

    await renderRules();
    await screen.findByTestId('rules-list');

    expect(screen.queryByText(/field_presence/)).toBeNull();
    expect(screen.queryByText(/net_quantity/)).toBeNull();
    expect(screen.queryByText(/named reviewer/)).toBeNull();
  });

  it('says that nothing is decided on the phone, and that a check is narrower than its clause', async () => {
    serveRules();

    await renderRules();

    const footnote = screen.getByTestId('rules-footnote');
    expect(footnote).toHaveTextContent('Nothing is decided on this phone', { exact: false });
    expect(footnote).toHaveTextContent('more narrowly than its clause requires', { exact: false });
  });
});

describe('an empty inventory', () => {
  it('says the server reports no rules, and invents none', async () => {
    serveRules([]);

    await renderRules();

    expect(await screen.findByTestId('rules-empty')).toHaveTextContent(
      'The server reports that it has no compliance rules loaded.',
      { exact: false },
    );
    expect(screen.getByTestId('rule-counts-summary')).toHaveTextContent(/0\s*TOTAL/);
    expect(screen.queryByTestId('rules-list')).toBeNull();
    expect(screen.queryAllByTestId(/^rule-LM-/)).toHaveLength(0);
  });
});

describe('when the list cannot be loaded', () => {
  it('says the current rule list was not loaded, shows no rules, and offers a retry', async () => {
    fetchMock.mockRejectedValue(new TypeError('Network request failed'));

    await renderRules();

    const error = await screen.findByTestId('rules-error');
    expect(error).toHaveTextContent('No connection', { exact: false });
    expect(error).toHaveTextContent('current rule list could not be loaded', { exact: false });
    expect(error).toHaveTextContent(host, { exact: false });
    expect(screen.getByTestId('rules-retry')).toBeOnTheScreen();
    expect(screen.queryByTestId('rule-counts-summary')).toBeNull();
    expect(screen.queryAllByTestId(/^rule-LM-/)).toHaveLength(0);
    expect(screen.queryByTestId('rules-source')).toBeNull();
  });

  it('loads the list on retry, passing through loading and leaving no error behind', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network request failed'));
    await renderRules();
    await screen.findByTestId('rules-error');

    const pending = holdNextResponse();
    await fireEvent.press(screen.getByTestId('rules-retry'));

    expect(screen.getByTestId('rules-loading')).toBeOnTheScreen();
    expect(screen.queryByTestId('rules-error')).toBeNull();

    pending.release(jsonResponse(rulesPageBody()));
    await screen.findByTestId('rules-list');

    expect(screen.queryByTestId('rules-error')).toBeNull();
    expect(renderedCodes()).toEqual(ruleInventoryBody().map((rule) => rule.code));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('refuses a malformed response without crashing, and shows none of it', async () => {
    // One good rule and one broken one. Showing the good one alone would present
    // an incomplete list as the server's inventory.
    fetchMock.mockResolvedValue(
      jsonResponse(rulesPageBody([ruleBody({ code: 'LM-PC-0001' }), { code: 'LM-PC-0002', is_active: 'yes' }])),
    );

    await renderRules();

    expect(await screen.findByTestId('rules-error')).toHaveTextContent('Unexpected response', { exact: false });
    expect(screen.queryByTestId('rule-LM-PC-0001')).toBeNull();
    expect(screen.getByTestId('rules-retry')).toBeOnTheScreen();
  });

  it('refuses a body that is not a page at all', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'something else entirely' }));

    await renderRules();

    expect(await screen.findByTestId('rules-error')).toBeOnTheScreen();
    expect(screen.queryByTestId('rule-counts-summary')).toBeNull();
  });

  it('explains a timeout without the analysis wording about photographs', async () => {
    // Found on an emulator: a request that stalls until the client's timeout got
    // the shared message, which blames "a very large photo". No photo is involved.
    fetchMock.mockRejectedValue(Object.assign(new Error('aborted'), { name: 'AbortError' }));

    await renderRules();

    const error = await screen.findByTestId('rules-error');
    expect(error).toHaveTextContent('The server took too long', { exact: false });
    expect(error).toHaveTextContent('slow connection', { exact: false });
    expect(error).not.toHaveTextContent(/photo|analysis/i);
    expect(screen.getByTestId('rules-retry')).toBeOnTheScreen();
  });

  it('reports a server failure as one, with a retry', async () => {
    fetchMock.mockResolvedValue(jsonResponse(errorEnvelope('server_error', 'A server error occurred.'), { status: 500 }));

    await renderRules();

    expect(await screen.findByTestId('rules-error')).toHaveTextContent('Server problem', { exact: false });
    expect(screen.getByTestId('rules-retry')).toBeOnTheScreen();
  });

  it('says a server that requires sign-in will not show its list, without a pointless retry', async () => {
    // What a deployment with the demonstration switch off answers.
    fetchMock.mockResolvedValue(
      jsonResponse(errorEnvelope('not_authenticated', 'Authentication credentials were not provided.'), {
        status: 403,
      }),
    );

    await renderRules();

    const error = await screen.findByTestId('rules-error');
    expect(error).toHaveTextContent('Rule list not available', { exact: false });
    expect(error).toHaveTextContent('signed-in users', { exact: false });
    expect(screen.queryByTestId('rules-retry')).toBeNull();
    expect(screen.queryAllByTestId(/^rule-LM-/)).toHaveLength(0);
  });

  it('says a server without the endpoint does not provide a list', async () => {
    fetchMock.mockResolvedValue(jsonResponse(errorEnvelope('not_found', 'Not found.'), { status: 404 }));

    await renderRules();

    expect(await screen.findByTestId('rules-error')).toHaveTextContent('does not provide a rule list', {
      exact: false,
    });
  });
});

it('names the screen as before', async () => {
  serveRules();

  await renderRules();

  expect(screen.getByRole('header', { name: 'Rules & information' })).toBeOnTheScreen();
});
