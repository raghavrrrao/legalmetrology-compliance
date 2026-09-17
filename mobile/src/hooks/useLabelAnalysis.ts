/**
 * The two-step analysis flow: read the label, then ask what the rules make of it.
 *
 *     photo -> POST /api/v1/extraction/ -> ExtractionRun id
 *                                       -> POST /api/v1/compliance/ -> verdict
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
 * 1. **The photograph is uploaded once.** The run id from step one is held
 *    here and passed to step two. Re-checking never re-uploads.
 * 2. **One compliance request per evaluation.** A second `evaluate` while one
 *    is in flight is dropped, not queued - each POST creates a stored result.
 * 3. **A failed verdict does not discard the reading.** If extraction
 *    succeeded and the compliance call failed, the reading stays and `retry`
 *    reuses the same run.
 *
 * This is also the seam the future review step plugs into. When the backend
 * classifies a product with low confidence, a screen can show the suggestion,
 * ask the person to confirm, and call `evaluate({ categoryCode })` on the same
 * run - no new upload, no new endpoint. Nothing in this hook copies a
 * classifier's suggestion into a request on its own.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { evaluateExtractionRun } from '../api/compliance';
import { extractLabel } from '../api/extraction';
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
  /** A `ProductImage.ViewType` value. */
  viewType?: string;
  /** A `ProductCategory.code` the person supplied. Empty means unknown. */
  categoryCode?: string;
}

export interface LabelAnalysis {
  phase: AnalysisPhase;
  /** The photograph as picked on the device, for previews. */
  image: SelectedImage | null;
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
  /** Upload a photograph, read it, and evaluate the reading. */
  analyse: (image: SelectedImage, options?: AnalysisOptions) => Promise<void>;
  /** Re-check the reading already held. Never re-uploads. */
  evaluate: (options?: Pick<AnalysisOptions, 'categoryCode'>) => Promise<void>;
  /** Repeat whichever step failed, with the same inputs. */
  retry: () => Promise<void>;
  reset: () => void;
}

export function useLabelAnalysis(): LabelAnalysis {
  const [phase, setPhase] = useState<AnalysisPhase>('idle');
  const [image, setImage] = useState<SelectedImage | null>(null);
  const [extraction, setExtraction] = useState<ExtractionRun | null>(null);
  const [storedImage, setStoredImage] = useState<ProductImage | null>(null);
  const [result, setResult] = useState<ComplianceResult | null>(null);
  const [extractionError, setExtractionError] = useState<unknown>(null);
  const [complianceError, setComplianceError] = useState<unknown>(null);
  const [categoryCode, setCategoryCode] = useState('');

  // The id the compliance call needs, and the inputs a retry repeats. Refs so
  // the callbacks below are stable and can read the latest values.
  const runIdRef = useRef<string | null>(null);
  const imageRef = useRef<SelectedImage | null>(null);
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
    imageRef.current = null;
    optionsRef.current = {};
    evaluatingRef.current = false;
    setPhase('idle');
    setImage(null);
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
    async (nextImage: SelectedImage, options: AnalysisOptions = {}) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      runIdRef.current = null;
      imageRef.current = nextImage;
      optionsRef.current = { ...options, categoryCode: (options.categoryCode ?? '').trim() };
      evaluatingRef.current = false;

      setPhase('extracting');
      setImage(nextImage);
      setCategoryCode(optionsRef.current.categoryCode ?? '');
      setExtractionError(null);
      setComplianceError(null);
      // Cleared so a previous verdict cannot sit next to a new photograph and
      // be read as belonging to it.
      setResult(null);
      setExtraction(null);
      setStoredImage(null);

      let run: Awaited<ReturnType<typeof extractLabel>>;
      try {
        run = await extractLabel(
          { uri: nextImage.uri, name: nextImage.name, type: nextImage.type },
          { viewType: options.viewType, signal: controller.signal },
        );
      } catch (cause) {
        if (mountedRef.current) {
          logError('extraction', cause);
          setExtractionError(cause);
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
    if (imageRef.current) {
      await analyse(imageRef.current, optionsRef.current);
    }
  }, [analyse, evaluate]);

  return {
    phase,
    image,
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
