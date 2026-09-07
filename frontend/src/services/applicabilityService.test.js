/**
 * The applicability catalogue client.
 *
 * The assertions that matter here are about what this module refuses to do:
 * it must not invent a condition, must not invent an answer, and must not turn
 * a malformed response into a screen crash. The catalogue is legal content and
 * the browser is not allowed to author any of it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchApplicabilityConditions } from './applicabilityService.js';
import { applicabilityBody, applicabilityConditionBody } from '../test/fixtures.js';

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

describe('fetchApplicabilityConditions', () => {
  it('requests the discovery endpoint under the compliance prefix', async () => {
    fetch.mockResolvedValue(jsonResponse(applicabilityBody()));

    await fetchApplicabilityConditions();

    const [url, init] = fetch.mock.calls[0];
    expect(url).toContain('/api/v1/compliance/applicability-conditions/');
    expect(init.method).toBe('GET');
  });

  it('maps a condition field for field', async () => {
    fetch.mockResolvedValue(
      jsonResponse(applicabilityBody({ conditions: [applicabilityConditionBody()] })),
    );

    const { conditions } = await fetchApplicabilityConditions();

    expect(conditions).toHaveLength(1);
    expect(conditions[0]).toEqual({
      code: 'imported-product',
      name: 'Imported product or imported package',
      description: 'Whether this package was imported into India.',
      determination: 'user_declared',
      determinationNote: 'Nothing on the label establishes import status.',
      scope: 'clause',
      answers: ['yes', 'no', 'unknown'],
      affects: [
        {
          clause: '6(1)(aa)',
          mode: 'requires',
          modeDisplay: 'Applies only to',
          note: 'Applies to imported products only.',
          ruleCodes: ['LM-PC-0007'],
        },
      ],
    });
  });

  it('carries the answer semantics through rather than restating them', async () => {
    fetch.mockResolvedValue(jsonResponse(applicabilityBody()));

    const { answerSemantics } = await fetchApplicabilityConditions();

    expect(answerSemantics.unknown).toContain('never read as');
  });

  it('distinguishes an unloaded framework from an empty catalogue', async () => {
    fetch.mockResolvedValue(
      jsonResponse(applicabilityBody({ conditions: [], framework_loaded: false })),
    );

    const catalogue = await fetchApplicabilityConditions();

    expect(catalogue.conditions).toEqual([]);
    expect(catalogue.frameworkLoaded).toBe(false);
  });

  it('survives a malformed response rather than taking the screen down', async () => {
    // The declarations are optional. A broken catalogue must cost the user the
    // form, not the ability to analyse a label.
    fetch.mockResolvedValue(jsonResponse({ conditions: 'not-a-list' }));

    const catalogue = await fetchApplicabilityConditions();

    expect(catalogue.conditions).toEqual([]);
    expect(catalogue.answerSemantics).toEqual({});
    expect(catalogue.frameworkLoaded).toBe(false);
  });

  it('treats an unrecognised scope as clause-level, which understates it', async () => {
    // Being wrong in this direction says an answer does less than it does,
    // which is the safe way to be wrong about a scope gate.
    fetch.mockResolvedValue(
      jsonResponse(
        applicabilityBody({
          conditions: [applicabilityConditionBody({ scope: 'something_new' })],
        }),
      ),
    );

    const { conditions } = await fetchApplicabilityConditions();

    expect(conditions[0].scope).toBe('clause');
  });

  it('never fabricates an answer vocabulary for a condition that has none', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        applicabilityBody({
          conditions: [applicabilityConditionBody({ answers: undefined })],
        }),
      ),
    );

    const { conditions } = await fetchApplicabilityConditions();

    // Falls back to the three the API defines, and to nothing wider. A fourth
    // answer would have to come from the backend.
    expect(conditions[0].answers).toEqual(['yes', 'no', 'unknown']);
  });
});
