/**
 * The two-step analysis flow: read the label, then ask what the rules make of it.
 *
 *     photos -> POST /api/v1/extraction/ -> ExtractionRun id
 *                                        -> POST /api/v1/compliance/ -> verdict
 *
 * **One inspection, however many photographs.** The set is uploaded in one
 * request and read into one `ExtractionRun`, so there is one reading and one
 * verdict about the package - never one per photograph. Nothing in this hook
 * combines results, because there is never more than one to combine.
 *
 * Two requests rather than the one-shot `POST /api/v1/images/`, for the reason
 * docs/api.md gives and the web client follows: the reading and the verdict
 * are different claims, and this flow can show honestly which one is in
 * flight - "reading the label" and "checking the requirements" fail for
 * different reasons and want different messages. The progress the user sees
 * is these two real states, not an animated percentage.
 *
 * Three properties this hook guarantees, mirroring
 * `frontend/src/hooks/useLabelAnalysis.js`:
 *
 * 1. **The photographs are uploaded once.** The run id from step one is held
 *    here and passed to step two. Re-checking never re-uploads.
 * 2. **One compliance request per evaluation.** A second `evaluate` while one
 *    is in flight is dropped, not queued - each POST creates a stored result.
 * 3. **A failed verdict does not discard the reading.** If extraction
 *    succeeded and the compliance call failed, the reading stays and `retry`
 *    reuses the same run.
 * 4. **A failed upload does not discard the user's photographs.** `images`
 *    keeps the set that was submitted, and `retry` sends exactly that set
 *    again. Someone who photographed four panels on a bad connection must not
 *    have to photograph them a second time.
 *
 * This is also the seam the future review step plugs into. When the backend
 * classifies a product with low confidence, a screen can show the suggestion,
 * ask the person to confirm, and call `evaluate({ categoryCode })` on the same
 * run - no new upload, no new endpoint. Nothing in this hook copies a
 * classifier's suggestion into a request on its own.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { evaluateExtractionRun } from '../api/compliance';
import { extractPackage } from '../api/extraction';
import type { SelectedImage } from '../services/imageValidation';
import type { ComplianceResult, ExtractionRun, ProductImage } from '../types/api';
import { logError } from '../utils/errors';

/**
 * Where the flow is. `extracted` is a real resting state: the reading exists
 * and the verdict has not been produced (either not yet asked for, or asked
 * for and failed).
 */
export type AnalysisPhase = 'idle' | 'extracting' | 'extracted' | 'evaluating' | 'complete';

export interface AnalysisOptions {
  /**
   * A `ProductImage.ViewType` per photograph, positionally. The app does not
   * ask which panel is which today, so this is normally left unset and every
   * photograph is recorded as `unspecified` - which is honest. It is never
   * inferred from the order: the second photograph a person takes is not
   * necessarily the back.
   */
  viewTypes?: (string | undefined)[];
  /** A `ProductCategory.code` the person supplied. Empty means unknown. */
  categoryCode?: string;
}

export interface LabelAnalysis {
  phase: AnalysisPhase;
  /**
   * The primary photograph as picked on the device, for a single preview.
   * `images[0]`, or null before anything was submitted.
   */
  image: SelectedImage | null;
  /**
   * Every photograph submitted for this inspection, in order, as picked on the
   * device. Kept across a failure so a retry costs the user nothing.
   */
  images: SelectedImage[];
  /** The reading. Present from the moment extraction succeeds. */
  extraction: ExtractionRun | null;
  /** The stored photograph's measured facts, as the backend recorded them. */
  storedImage: ProductImage | null;
  /** The verdict, findings and violations. Null until compliance succeeds. */
  result: ComplianceResult | null;
  extractionError: unknown;
  complianceError: unknown;
  /** The category code the most recent evaluation was asked with ('' if none). */
  categoryCode: string;
  isExtracting: boolean;
  isEvaluating: boolean;
  isBusy: boolean;
  /**
   * Upload the photographs of one package, read them, and evaluate the
   * reading. Accepts one photograph or a set; a single one is the set of one.
   */
  analyse: (images: SelectedImage | SelectedImage[], options?: AnalysisOptions) => Promise<void>;
  /** Re-check the reading already held. Never re-uploads. */
  evaluate: (options?: Pick<AnalysisOptions, 'categoryCode'>) => Promise<void>;
  /** Repeat whichever step failed, with the same inputs. */
  retry: () => Promise<void>;
  reset: () => void;
}

export function useLabelAnalysis(): LabelAnalysis {
  const [phase, setPhase] = useState<AnalysisPhase>('idle');
  const [images, setImages] = useState<SelectedImage[]>([]);
  const [extraction, setExtraction] = useState<ExtractionRun | null>(null);
  const [storedImage, setStoredImage] = useState<ProductImage | null>(null);
  const [result, setResult] = useState<ComplianceResult | null>(null);
  const [extractionError, setExtractionError] = useState<unknown>(null);
  const [complianceError, setComplianceError] = useState<unknown>(null);
  const [categoryCode, setCategoryCode] = useState('');

  // The id the compliance call needs, and the inputs a retry repeats. Refs so
  // the callbacks below are stable and can read the latest values.
  const runIdRef = useRef<string | null>(null);
  const imagesRef = useRef<SelectedImage[]>([]);
  const optionsRef = useRef<AnalysisOptions>({});
  // Guards property 2. A ref rather than state: two taps in the same tick both
  // see the old state value, and both would post.
  const evaluatingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    runIdRef.current = null;
    imagesRef.current = [];
    optionsRef.current = {};
    evaluatingRef.current = false;
    setPhase('idle');
    setImages([]);
    setExtraction(null);
    setStoredImage(null);
    setResult(null);
    setExtractionError(null);
    setComplianceError(null);
    setCategoryCode('');
  }, []);

  const evaluate = useCallback(async (options: Pick<AnalysisOptions, 'categoryCode'> = {}) => {
    const runId = runIdRef.current;
    if (!runId || evaluatingRef.current) {
      return;
    }

    const nextCategory = (options.categoryCode ?? optionsRef.current.categoryCode ?? '').trim();
    optionsRef.current = { ...optionsRef.current, categoryCode: nextCategory };

    evaluatingRef.current = true;
    setComplianceError(null);
    setCategoryCode(nextCategory);
    setPhase('evaluating');

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const evaluated = await evaluateExtractionRun(runId, {
        categoryCode: nextCategory || undefined,
        signal: controller.signal,
      });
      if (!mountedRef.current) {
        return;
      }
      setResult(evaluated);
      // The result carries its own copy of the reading, mapped by the same
      // code. Adopting it keeps the reading and the verdict provably about the
      // same run.
      if (evaluated.extraction) {
        setExtraction(evaluated.extraction);
      }
      if (evaluated.image) {
        setStoredImage(evaluated.image);
      }
      setPhase('complete');
    } catch (cause) {
      if (!mountedRef.current) {
        return;
      }
      logError('compliance', cause);
      setComplianceError(cause);
      // Back to the reading, not to nothing: the extraction is still valid and
      // retrying reuses the same run.
      setPhase('extracted');
    } finally {
      evaluatingRef.current = false;
    }
  }, []);

  const analyse = useCallback(
    async (nextImages: SelectedImage | SelectedImage[], options: AnalysisOptions = {}) => {
      const submitted = Array.isArray(nextImages) ? [...nextImages] : [nextImages];

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      runIdRef.current = null;
      imagesRef.current = submitted;
      optionsRef.current = { ...options, categoryCode: (options.categoryCode ?? '').trim() };
      evaluatingRef.current = false;

      setPhase('extracting');
      setImages(submitted);
      setCategoryCode(optionsRef.current.categoryCode ?? '');
      setExtractionError(null);
      setComplianceError(null);
      // Cleared so a previous verdict cannot sit next to new photographs and
      // be read as belonging to them.
      setResult(null);
      setExtraction(null);
      setStoredImage(null);

      let run: Awaited<ReturnType<typeof extractPackage>>;
      try {
        run = await extractPackage(
          submitted.map((picked) => ({ uri: picked.uri, name: picked.name, type: picked.type })),
          { viewTypes: options.viewTypes, signal: controller.signal },
        );
      } catch (cause) {
        if (mountedRef.current) {
          logError('extraction', cause);
          setExtractionError(cause);
          // Back to idle, but `images` is deliberately left as it is: the
          // user's photographs are still theirs, and `retry` resends exactly
          // this set without asking them to choose again.
          setPhase('idle');
        }
        return;
      }

      if (!mountedRef.current) {
        return;
      }

      runIdRef.current = run.id;
      setExtraction(run);
      setStoredImage(run.image);
      setPhase('extracted');

      await evaluate({ categoryCode: optionsRef.current.categoryCode });
    },
    [evaluate],
  );

  const retry = useCallback(async () => {
    if (runIdRef.current) {
      await evaluate();
      return;
    }
    if (imagesRef.current.length > 0) {
      // The same set, in the same order. A retry must not quietly send a
      // different inspection from the one that failed.
      await analyse(imagesRef.current, optionsRef.current);
    }
  }, [analyse, evaluate]);

  return {
    phase,
    image: images[0] ?? null,
    images,
    extraction,
    storedImage,
    result,
    extractionError,
    complianceError,
    categoryCode,
    isExtracting: phase === 'extracting',
    isEvaluating: phase === 'evaluating',
    isBusy: phase === 'extracting' || phase === 'evaluating',
    analyse,
    evaluate,
    retry,
    reset,
  };
}
