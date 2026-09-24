/**
 * The rule inventory client: the request sent, the mapping, pagination, and
 * every response it must refuse rather than show.
 *
 * Over a stubbed `fetch` and the real `apiClient`, so the URL joining, the
 * error envelope and the status handling under test are the ones the app uses.
 */

import { ApiError } from './client';
import { fetchRuleInventory, mapRule, MAX_RULE_PAGES, RULES_PAGE_SIZE } from './rules';
import { errorEnvelope, jsonResponse, ruleBody, ruleInventoryBody, rulesPageBody } from '../../tests/fixtures';
import { config } from '../config/env';

const fetchMock = jest.fn();

beforeEach(() => {
  (globalThis as unknown as { fetch: unknown }).fetch = fetchMock;
});

const firstPageUrl = `${config.apiBaseUrl}rules/?page_size=${RULES_PAGE_SIZE}`;

/** A `next` link as the backend builds it: absolute, on the same server. */
function nextLink(page: number): string {
  return `${config.apiBaseUrl}rules/?page=${page}&page_size=${RULES_PAGE_SIZE}`;
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(
    () => {
      throw new Error('expected the inventory to be refused');
    },
    (caught: unknown) => caught,
  );
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

describe('the request', () => {
  it('gets rules/ at the largest page size, with no body and no credentials', async () => {
    fetchMock.mockResolvedValue(jsonResponse(rulesPageBody()));

    await fetchRuleInventory();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(firstPageUrl);
    expect(init.method).toBe('GET');
    expect(init.body).toBeUndefined();
    expect(init.headers.Authorization).toBeUndefined();
    expect(init.credentials).toBeUndefined();
  });

  it('requests nothing but the rule inventory', async () => {
    fetchMock.mockResolvedValue(jsonResponse(rulesPageBody()));

    await fetchRuleInventory();

    for (const [url] of fetchMock.mock.calls) {
      expect(url).toMatch(/\/rules\/\?/);
      expect(url).not.toMatch(/compliance|images|extraction|health/);
    }
  });

  it('passes the caller’s cancellation through', async () => {
    fetchMock.mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
        }),
    );
    const controller = new AbortController();

    const pending = fetchRuleInventory({ signal: controller.signal });
    controller.abort();

    const error = await rejection(pending);
    expect(error.code).toBe('timeout');
  });
});

describe('mapping', () => {
  it('maps every field from snake_case to the app’s camelCase, verbatim', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        rulesPageBody([
          ruleBody({
            code: 'LM-PC-0002',
            title: 'Common or generic name of the commodity',
            legal_reference: 'Rule 6(1)(b) of the Legal Metrology (Packaged Commodities) Rules, 2011',
            clause: '6(1)(b)',
            source_status: 'verified',
            is_active: false,
            effective_from: '2011-04-01',
            effective_to: null,
          }),
        ]),
      ),
    );

    const inventory = await fetchRuleInventory();

    expect(inventory.rules).toEqual([
      {
        code: 'LM-PC-0002',
        title: 'Common or generic name of the commodity',
        legalReference: 'Rule 6(1)(b) of the Legal Metrology (Packaged Commodities) Rules, 2011',
        clause: '6(1)(b)',
        sourceStatus: 'verified',
        isActive: false,
        effectiveFrom: '2011-04-01',
        effectiveTo: null,
      },
    ]);
  });

  it('keeps a null clause null and a blank reference blank', () => {
    const rule = mapRule(ruleBody({ clause: null, legal_reference: '' }));

    expect(rule.clause).toBeNull();
    expect(rule.legalReference).toBe('');
  });

  it('copies only the contract’s eight fields, whatever else a server sends', () => {
    const rule = mapRule({
      ...ruleBody(),
      check_type: 'field_presence',
      parameters: { field_key: 'net_quantity', threshold: 7 },
      applies_to_categories: ['packaged-food'],
      source_note: 'Checked by a reviewer.',
    });

    expect(Object.keys(rule).sort()).toEqual(
      [
        'clause',
        'code',
        'effectiveFrom',
        'effectiveTo',
        'isActive',
        'legalReference',
        'sourceStatus',
        'title',
      ].sort(),
    );
  });

  it('keeps the server’s order rather than sorting', async () => {
    const rules = [ruleBody({ code: 'LM-PC-0009' }), ruleBody({ code: 'LM-PC-0001' })];
    fetchMock.mockResolvedValue(jsonResponse(rulesPageBody(rules)));

    const inventory = await fetchRuleInventory();

    expect(inventory.rules.map((rule) => rule.code)).toEqual(['LM-PC-0009', 'LM-PC-0001']);
  });

  it('reports the server’s count and tallies its is_active flags', async () => {
    fetchMock.mockResolvedValue(jsonResponse(rulesPageBody(ruleInventoryBody())));

    const inventory = await fetchRuleInventory();

    expect(inventory.total).toBe(4);
    expect(inventory.active).toBe(3);
    expect(inventory.inactive).toBe(1);
  });

  it('passes is_active through without consulting dates or status', async () => {
    // A rule whose window closed years ago, one not yet in force, and an
    // unverified one - all active on the server. Whether any of them applies to
    // a package is the engine's question; the client reports the flag.
    const rules = [
      ruleBody({ code: 'LM-PC-0001', effective_from: '2011-04-01', effective_to: '2012-01-01' }),
      ruleBody({ code: 'LM-PC-0002', effective_from: '2099-01-01' }),
      ruleBody({ code: 'LM-PC-0003', source_status: 'unverified' }),
    ];
    fetchMock.mockResolvedValue(jsonResponse(rulesPageBody(rules)));

    const inventory = await fetchRuleInventory();

    expect(inventory.rules.every((rule) => rule.isActive)).toBe(true);
    expect(inventory.active).toBe(3);
    expect(inventory.rules[2].sourceStatus).toBe('unverified');
  });

  it('accepts an empty inventory as an empty inventory', async () => {
    fetchMock.mockResolvedValue(jsonResponse(rulesPageBody([])));

    await expect(fetchRuleInventory()).resolves.toEqual({ rules: [], total: 0, active: 0, inactive: 0 });
  });
});

describe('pagination', () => {
  it('follows next to the end and returns every page, in order', async () => {
    const all = ruleInventoryBody();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(rulesPageBody(all.slice(0, 2), { count: 4, next: nextLink(2) })))
      .mockResolvedValueOnce(
        jsonResponse(rulesPageBody(all.slice(2), { count: 4, previous: firstPageUrl })),
      );

    const inventory = await fetchRuleInventory();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toBe(nextLink(2));
    expect(inventory.rules.map((rule) => rule.code)).toEqual(all.map((rule) => rule.code));
    expect(inventory.total).toBe(4);
  });

  it('does not stop at the first page when the server says there is more', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(rulesPageBody([ruleBody({ code: 'LM-PC-0001' })], { count: 2, next: nextLink(2) })))
      .mockResolvedValueOnce(jsonResponse(rulesPageBody([ruleBody({ code: 'LM-PC-0002' })], { count: 2 })));

    const inventory = await fetchRuleInventory();

    expect(inventory.rules).toHaveLength(2);
  });

  it('refuses a next link that points at a different server, without following it', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(rulesPageBody([ruleBody()], { count: 2, next: 'https://elsewhere.example/api/v1/rules/?page=2' })),
    );

    const error = await rejection(fetchRuleInventory());

    expect(error.code).toBe('unexpected_response');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('refuses pages that do not add up to the count', async () => {
    fetchMock.mockResolvedValue(jsonResponse(rulesPageBody([ruleBody()], { count: 3 })));

    expect((await rejection(fetchRuleInventory())).code).toBe('unexpected_response');
  });

  it('refuses an inventory whose count changes between pages', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(rulesPageBody([ruleBody({ code: 'LM-PC-0001' })], { count: 2, next: nextLink(2) })))
      .mockResolvedValueOnce(jsonResponse(rulesPageBody([ruleBody({ code: 'LM-PC-0002' })], { count: 3 })));

    expect((await rejection(fetchRuleInventory())).code).toBe('unexpected_response');
  });

  it('refuses a rule listed twice', async () => {
    fetchMock.mockResolvedValue(jsonResponse(rulesPageBody([ruleBody(), ruleBody()])));

    expect((await rejection(fetchRuleInventory())).code).toBe('unexpected_response');
  });

  it('stops when next leads back to a page already read', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(rulesPageBody([ruleBody()], { count: 5, next: nextLink(2) })),
    );

    const error = await rejection(fetchRuleInventory());

    expect(error.code).toBe('unexpected_response');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('stops after the page ceiling rather than loading for ever', async () => {
    let page = 1;
    fetchMock.mockImplementation(async () => {
      page += 1;
      return jsonResponse(
        rulesPageBody([ruleBody({ code: `LM-PC-${page}` })], { count: 100000, next: nextLink(page) }),
      );
    });

    const error = await rejection(fetchRuleInventory());

    expect(error.code).toBe('unexpected_response');
    expect(fetchMock).toHaveBeenCalledTimes(MAX_RULE_PAGES);
  });
});

describe('a malformed response', () => {
  it.each([
    ['a list instead of a page', ruleInventoryBody()],
    ['null', null],
    ['no count', { next: null, previous: null, results: [] }],
    ['a negative count', rulesPageBody([], { count: -1 })],
    ['a fractional count', rulesPageBody([], { count: 1.5 })],
    ['results that are not a list', { count: 0, next: null, previous: null, results: {} }],
    ['a next that is not a string', rulesPageBody([], { next: 2 as unknown as string })],
    ['more rules than the count', rulesPageBody([ruleBody()], { count: 0 })],
  ])('refuses %s', async (_label, body) => {
    fetchMock.mockResolvedValue(jsonResponse(body));

    const error = await rejection(fetchRuleInventory());

    expect(error.code).toBe('unexpected_response');
  });

  it.each([
    ['a rule that is not an object', 'LM-PC-0001'],
    ['a rule with no code', ruleBody({ code: '' })],
    ['a missing title', { ...ruleBody(), title: undefined }],
    ['a null legal reference', ruleBody({ legal_reference: null as unknown as string })],
    ['a missing clause', { ...ruleBody(), clause: undefined }],
    ['a numeric clause', ruleBody({ clause: 6 as unknown as string })],
    ['a status outside the contract', ruleBody({ source_status: 'requires_review' as 'verified' })],
    ['is_active as a string', ruleBody({ is_active: 'true' as unknown as boolean })],
    ['a date that is not an ISO date', ruleBody({ effective_from: '01/04/2011' })],
  ])('refuses the whole inventory for %s, rather than dropping the row', async (_label, bad) => {
    fetchMock.mockResolvedValue(jsonResponse(rulesPageBody([ruleBody({ code: 'LM-PC-0001' }), bad])));

    const error = await rejection(fetchRuleInventory());

    expect(error.code).toBe('unexpected_response');
  });

  it('refuses a 2xx body that is not JSON', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError('Unexpected token <');
      },
    });

    expect((await rejection(fetchRuleInventory())).code).toBe('invalid_json');
  });
});

describe('a failed request', () => {
  it('reports no connection as a network error', async () => {
    fetchMock.mockRejectedValue(new TypeError('Network request failed'));

    const error = await rejection(fetchRuleInventory());

    expect(error.code).toBe('network_error');
    expect(error.isNetworkError).toBe(true);
  });

  it('carries the backend’s envelope for a refusal', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(errorEnvelope('not_authenticated', 'Authentication credentials were not provided.'), {
        status: 403,
      }),
    );

    const error = await rejection(fetchRuleInventory());

    expect(error.status).toBe(403);
    expect(error.code).toBe('not_authenticated');
  });

  it('reports a server failure with its status', async () => {
    fetchMock.mockResolvedValue(jsonResponse(errorEnvelope('server_error', 'A server error occurred.'), { status: 500 }));

    expect((await rejection(fetchRuleInventory())).status).toBe(500);
  });

  it('fails the whole inventory when a later page fails', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(rulesPageBody([ruleBody({ code: 'LM-PC-0001' })], { count: 2, next: nextLink(2) })))
      .mockRejectedValueOnce(new TypeError('Network request failed'));

    expect((await rejection(fetchRuleInventory())).code).toBe('network_error');
  });
});
