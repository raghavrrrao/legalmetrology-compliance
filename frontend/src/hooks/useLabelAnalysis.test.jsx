/**
 * The two-step flow, at the level the UI cannot reach.
 *
 * The page tests assert what a user sees. These assert the three guarantees
 * that hold the flow together underneath: the photograph is uploaded once, one
 * compliance request is made per evaluation, and a failed verdict does not take
 * the reading with it.
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PHASES, useLabelAnalysis } from './useLabelAnalysis.js';
import { complianceBody, extractionBody } from '../test/fixtures.js';

function jsonResponse(body, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

function routeFetch({ extraction, compliance } = {}) {
  fetch.mockImplementation(async (url) => {
    const target = String(url);
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

const FILE = () => new File(['bytes'], 'label.png', { type: 'image/png' });

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('useLabelAnalysis', () => {
  it('starts idle with nothing loaded', () => {
    const { result } = renderHook(() => useLabelAnalysis());

    expect(result.current.phase).toBe(PHASES.IDLE);
    expect(result.current.extraction).toBeNull();
    expect(result.current.result).toBeNull();
    expect(result.current.isBusy).toBe(false);
  });

  it('extracts, then evaluates the run it was given', async () => {
    routeFetch();
    const { result } = renderHook(() => useLabelAnalysis());

    await act(async () => {
      await result.current.analyse(FILE(), { viewType: 'back' });
    });

    expect(result.current.phase).toBe(PHASES.COMPLETE);
    expect(callsTo('/extraction/')).toHaveLength(1);
    expect(callsTo('/compliance/')).toHaveLength(1);
    expect(JSON.parse(callsTo('/compliance/')[0][1].body)).toEqual({
      extraction_run_id: extractionBody().id,
    });
    expect(result.current.result.id).toBe(complianceBody().id);
  });

  it('sends the view type on the extraction request only', async () => {
    routeFetch();
    const { result } = renderHook(() => useLabelAnalysis());

    await act(async () => {
      await result.current.analyse(FILE(), {
        viewType: 'front',
        categoryCode: 'packaged-food',
      });
    });

    expect(callsTo('/extraction/')[0][1].body.get('view_type')).toBe('front');
    // The extraction endpoint takes no category: a category selects which rules
    // apply, and no rule is consulted when reading a label.
    expect(callsTo('/extraction/')[0][1].body.get('category_code')).toBeNull();
    expect(JSON.parse(callsTo('/compliance/')[0][1].body).category_code).toBe(
      'packaged-food',
    );
  });

  it('omits an empty category rather than sending a blank one', async () => {
    routeFetch();
    const { result } = renderHook(() => useLabelAnalysis());

    await act(async () => {
      await result.current.analyse(FILE(), { categoryCode: '' });
    });

    expect(JSON.parse(callsTo('/compliance/')[0][1].body)).toEqual({
      extraction_run_id: extractionBody().id,
    });
  });

  it('re-evaluates without re-uploading', async () => {
    routeFetch();
    const { result } = renderHook(() => useLabelAnalysis());

    await act(async () => {
      await result.current.analyse(FILE());
    });
    await act(async () => {
      await result.current.evaluate({ categoryCode: 'packaged-food' });
    });

    expect(callsTo('/extraction/')).toHaveLength(1);
    expect(callsTo('/compliance/')).toHaveLength(2);
    // Both evaluations concern the same reading, which is the whole point of
    // holding the run id here.
    const runIds = callsTo('/compliance/').map(
      ([, init]) => JSON.parse(init.body).extraction_run_id,
    );
    expect(runIds).toEqual([extractionBody().id, extractionBody().id]);
  });

  it('drops a second evaluate while one is already in flight', async () => {
    let release;
    const pending = new Promise((resolve) => {
      release = resolve;
    });
    fetch.mockImplementation(async (url) => {
      if (String(url).includes('/extraction/')) {
        return jsonResponse(extractionBody(), 201);
      }
      await pending;
      return jsonResponse(complianceBody(), 201);
    });

    const { result } = renderHook(() => useLabelAnalysis());

    let analysis;
    await act(async () => {
      analysis = result.current.analyse(FILE());
      // Let extraction settle so a run id exists to evaluate.
      await Promise.resolve();
    });

    await waitFor(() => expect(callsTo('/compliance/')).toHaveLength(1));

    await act(async () => {
      // A second ask while the first is unresolved. Each POST creates a
      // ComplianceCheck row, so this must not reach the network.
      await result.current.evaluate();
      release();
      await analysis;
    });

    expect(callsTo('/compliance/')).toHaveLength(1);
  });

  it('does nothing when evaluate is called before anything was extracted', async () => {
    routeFetch();
    const { result } = renderHook(() => useLabelAnalysis());

    await act(async () => {
      await result.current.evaluate();
    });

    expect(fetch).not.toHaveBeenCalled();
    expect(result.current.phase).toBe(PHASES.IDLE);
  });

  it('returns to idle and asks for no verdict when extraction fails', async () => {
    routeFetch({
      extraction: jsonResponse(
        { error: { code: 'validation_error', message: 'Unsupported file.' } },
        400,
      ),
    });
    const { result } = renderHook(() => useLabelAnalysis());

    await act(async () => {
      await result.current.analyse(FILE());
    });

    expect(result.current.phase).toBe(PHASES.IDLE);
    expect(result.current.extractionError.message).toBe('Unsupported file.');
    expect(result.current.extraction).toBeNull();
    expect(callsTo('/compliance/')).toHaveLength(0);
  });

  it('keeps the reading when only the compliance call fails', async () => {
    routeFetch({
      compliance: jsonResponse(
        { error: { code: 'validation_error', message: 'Unknown category.' } },
        400,
      ),
    });
    const { result } = renderHook(() => useLabelAnalysis());

    await act(async () => {
      await result.current.analyse(FILE());
    });

    // Back to the reading, not to nothing.
    expect(result.current.phase).toBe(PHASES.EXTRACTED);
    expect(result.current.extraction.id).toBe(extractionBody().id);
    expect(result.current.result).toBeNull();
    expect(result.current.complianceError.message).toBe('Unknown category.');
  });

  it('adopts the reading embedded in the result', async () => {
    routeFetch();
    const { result } = renderHook(() => useLabelAnalysis());

    await act(async () => {
      await result.current.analyse(FILE());
    });

    // Same run, mapped by the same code, so the reading on screen and the
    // reading the findings cite are provably the same one.
    expect(result.current.extraction.id).toBe(result.current.result.extraction.id);
  });

  it('clears everything on reset', async () => {
    routeFetch();
    const { result } = renderHook(() => useLabelAnalysis());

    await act(async () => {
      await result.current.analyse(FILE());
    });
    act(() => result.current.reset());

    expect(result.current.phase).toBe(PHASES.IDLE);
    expect(result.current.result).toBeNull();
    expect(result.current.extraction).toBeNull();

    // And the run id is gone with it: evaluating after a reset must not
    // silently re-check the previous photograph.
    await act(async () => {
      await result.current.evaluate();
    });
    expect(callsTo('/compliance/')).toHaveLength(1);
  });

  it('settles safely when unmounted with a request in flight', async () => {
    let release;
    const pending = new Promise((resolve) => {
      release = resolve;
    });
    fetch.mockImplementation(async (url) => {
      if (String(url).includes('/extraction/')) {
        await pending;
        return jsonResponse(extractionBody(), 201);
      }
      return jsonResponse(complianceBody(), 201);
    });

    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { result, unmount } = renderHook(() => useLabelAnalysis());

    let analysis;
    await act(async () => {
      analysis = result.current.analyse(FILE());
    });

    unmount();

    await act(async () => {
      release();
      await analysis;
    });

    // The hook aborts on unmount and guards every setState behind a mounted
    // check, so a late response neither throws nor reaches React.
    expect(errorSpy).not.toHaveBeenCalled();
    // And it did not carry on into the second request after being torn down.
    expect(callsTo('/compliance/')).toHaveLength(0);
  });
});
