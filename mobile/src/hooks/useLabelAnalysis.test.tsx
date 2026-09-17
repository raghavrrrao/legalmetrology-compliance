/**
 * The two-step flow, end to end over a stubbed `fetch`.
 *
 * The real API modules run - the mapping is part of what is under test - and
 * only the network is replaced. The assertions are about the three
 * guarantees in the hook's docstring: one upload, one evaluation at a time,
 * and a failed verdict keeping the reading.
 */

import { act, renderHook, waitFor } from '@testing-library/react-native';

import { useLabelAnalysis } from './useLabelAnalysis';
import { complianceBody, errorEnvelope, extractionBody, jsonResponse, RUN_ID, selectedImage } from '../../tests/fixtures';

const fetchMock = jest.fn();

beforeEach(() => {
  (globalThis as unknown as { fetch: unknown }).fetch = fetchMock;
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('useLabelAnalysis', () => {
  it('starts idle', async () => {
    const { result } = await renderHook(() => useLabelAnalysis());

    expect(result.current.phase).toBe('idle');
    expect(result.current.result).toBeNull();
    expect(result.current.isBusy).toBe(false);
  });

  it('moves through extracting -> extracted -> evaluating -> complete', async () => {
    const extraction = deferred<Response>();
    const compliance = deferred<Response>();
    fetchMock.mockReturnValueOnce(extraction.promise).mockReturnValueOnce(compliance.promise);

    const { result } = await renderHook(() => useLabelAnalysis());

    let pending!: Promise<void>;
    await act(async () => {
      pending = result.current.analyse(selectedImage(), { categoryCode: 'packaged-food' });
    });
    expect(result.current.phase).toBe('extracting');
    expect(result.current.isExtracting).toBe(true);
    expect(result.current.image?.name).toBe('label.jpg');

    await act(async () => {
      extraction.resolve(jsonResponse(extractionBody(), { status: 201 }));
    });
    await waitFor(() => expect(result.current.phase).toBe('evaluating'));
    expect(result.current.extraction?.id).toBe(RUN_ID);
    expect(result.current.storedImage?.width).toBe(1600);
    expect(result.current.result).toBeNull();

    await act(async () => {
      compliance.resolve(jsonResponse(complianceBody(), { status: 201 }));
      await pending;
    });

    expect(result.current.phase).toBe('complete');
    expect(result.current.result?.result).toBe('partially_compliant');
    expect(result.current.isBusy).toBe(false);

    // One upload, one evaluation, and the evaluation names the run the
    // upload returned, with the category the user gave.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/extraction\/$/);
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/compliance\/$/);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      extraction_run_id: RUN_ID,
      category_code: 'packaged-food',
    });
  });

  it('records a network failure on extraction and returns to idle', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network request failed'));

    const { result } = await renderHook(() => useLabelAnalysis());
    await act(async () => {
      await result.current.analyse(selectedImage());
    });

    expect(result.current.phase).toBe('idle');
    expect(result.current.extractionError).toMatchObject({ code: 'network_error', status: 0 });
    expect(result.current.extraction).toBeNull();
    expect(result.current.result).toBeNull();
    // The photo is kept, so a retry can repeat the upload.
    expect(result.current.image).not.toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('records an HTTP failure on extraction with the backend code', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(errorEnvelope('validation_error', 'The submitted data was not valid.', { image: ['Too large.'] }), {
        status: 400,
      }),
    );

    const { result } = await renderHook(() => useLabelAnalysis());
    await act(async () => {
      await result.current.analyse(selectedImage());
    });

    expect(result.current.extractionError).toMatchObject({ status: 400, code: 'validation_error' });
    expect(result.current.phase).toBe('idle');
  });

  it('keeps the reading when the compliance call fails, and retries without re-uploading', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(extractionBody(), { status: 201 }))
      .mockResolvedValueOnce(jsonResponse({ detail: 'Server Error (500)' }, { status: 500 }))
      .mockResolvedValueOnce(jsonResponse(complianceBody(), { status: 201 }));

    const { result } = await renderHook(() => useLabelAnalysis());
    await act(async () => {
      await result.current.analyse(selectedImage());
    });

    expect(result.current.phase).toBe('extracted');
    expect(result.current.extraction?.id).toBe(RUN_ID);
    expect(result.current.complianceError).toMatchObject({ status: 500 });
    expect(result.current.result).toBeNull();

    await act(async () => {
      await result.current.retry();
    });

    expect(result.current.phase).toBe('complete');
    expect(result.current.complianceError).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    // The third call is a compliance POST for the same run, not a new upload.
    expect(fetchMock.mock.calls[2][0]).toMatch(/\/compliance\/$/);
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ extraction_run_id: RUN_ID });
  });

  it('retries a failed upload by uploading again', async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError('Network request failed'))
      .mockResolvedValueOnce(jsonResponse(extractionBody(), { status: 201 }))
      .mockResolvedValueOnce(jsonResponse(complianceBody(), { status: 201 }));

    const { result } = await renderHook(() => useLabelAnalysis());
    await act(async () => {
      await result.current.analyse(selectedImage(), { categoryCode: 'packaged-food' });
    });
    expect(result.current.extractionError).not.toBeNull();

    await act(async () => {
      await result.current.retry();
    });

    expect(result.current.phase).toBe('complete');
    expect(result.current.extractionError).toBeNull();
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/extraction\/$/);
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({
      extraction_run_id: RUN_ID,
      category_code: 'packaged-food',
    });
  });

  it('re-evaluates the same reading with a category a person confirmed', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(extractionBody(), { status: 201 }))
      .mockResolvedValueOnce(jsonResponse(complianceBody({ product_category_code: null, result: 'review_required' }), { status: 201 }))
      .mockResolvedValueOnce(jsonResponse(complianceBody(), { status: 201 }));

    const { result } = await renderHook(() => useLabelAnalysis());
    await act(async () => {
      await result.current.analyse(selectedImage());
    });
    expect(result.current.result?.productCategoryCode).toBeNull();

    await act(async () => {
      await result.current.evaluate({ categoryCode: 'packaged-food' });
    });

    expect(result.current.categoryCode).toBe('packaged-food');
    expect(result.current.result?.productCategoryCode).toBe('packaged-food');
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({
      extraction_run_id: RUN_ID,
      category_code: 'packaged-food',
    });
  });

  it('drops a second evaluate while one is in flight', async () => {
    const compliance = deferred<Response>();
    fetchMock.mockResolvedValueOnce(jsonResponse(extractionBody(), { status: 201 })).mockReturnValueOnce(compliance.promise);

    const { result } = await renderHook(() => useLabelAnalysis());
    let pending!: Promise<void>;
    await act(async () => {
      pending = result.current.analyse(selectedImage());
    });
    await waitFor(() => expect(result.current.phase).toBe('evaluating'));

    await act(async () => {
      await result.current.evaluate();
      await result.current.evaluate();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      compliance.resolve(jsonResponse(complianceBody(), { status: 201 }));
      await pending;
    });
    expect(result.current.phase).toBe('complete');
  });

  it('does nothing on evaluate before any reading exists', async () => {
    const { result } = await renderHook(() => useLabelAnalysis());
    await act(async () => {
      await result.current.evaluate({ categoryCode: 'packaged-food' });
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.phase).toBe('idle');
  });

  it('reset clears everything', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(extractionBody(), { status: 201 }))
      .mockResolvedValueOnce(jsonResponse(complianceBody(), { status: 201 }));

    const { result } = await renderHook(() => useLabelAnalysis());
    await act(async () => {
      await result.current.analyse(selectedImage());
    });
    expect(result.current.result).not.toBeNull();

    await act(async () => {
      result.current.reset();
    });

    expect(result.current.phase).toBe('idle');
    expect(result.current.result).toBeNull();
    expect(result.current.extraction).toBeNull();
    expect(result.current.image).toBeNull();
  });
});
