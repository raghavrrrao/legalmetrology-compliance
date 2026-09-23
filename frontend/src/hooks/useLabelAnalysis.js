/**
 * The two-step analysis flow: read the label, then ask what the rules make of it.
 *
 *     files -> POST /api/v1/extraction/ -> ExtractionRun id
 *                                       -> POST /api/v1/compliance/ -> verdict
 *
 * **One inspection, however many photographs.** A packaged commodity declares
 * different things on different panels, so the set is uploaded in one request
 * and read into one `ExtractionRun` - one reading, one verdict about the
 * package, never one per photograph. Nothing here combines results, because
 * there is never more than one to combine.
 *
 * Follows the {data, error, isLoading, ...} shape `useApiHealth` set, extended
 * with the phase, because this flow has two requests and the user needs to know
 * which one is in flight - "reading the label" and "checking the rules" fail for
 * different reasons and want different messages.
 *
 * Three properties this hook exists to guarantee:
 *
 * 1. **The photograph is uploaded once.** The run id from step one is held here
 *    and passed to step two. Re-evaluating never re-uploads, so the reading the
 *    user is looking at is the reading the verdict was drawn from.
 * 2. **One compliance request per evaluation.** A second `evaluate` while one is
 *    in flight is dropped, not queued. Each POST creates a `ComplianceCheck`
 *    row, so a duplicate is not merely wasteful - it writes a second record of
 *    an evaluation nobody asked for.
 * 3. **A failed verdict does not discard the reading.** If extraction succeeded
 *    and the compliance call failed, the reading stays on screen with the error
 *    beside it and a retry that reuses the same run.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { evaluateExtractionRun } from '../services/complianceService.js';
import { extractPackage } from '../services/extractionService.js';

/**
 * Where the flow is. Ordered, and the UI's stepper reads it directly.
 *
 * `extracted` is a real resting state, not a transition: it is reached when the
 * reading is on screen and the verdict has not been asked for yet.
 */
export const PHASES = Object.freeze({
  IDLE: 'idle',
  EXTRACTING: 'extracting',
  EXTRACTED: 'extracted',
  EVALUATING: 'evaluating',
  COMPLETE: 'complete',
});

export function useLabelAnalysis() {
  const [phase, setPhase] = useState(PHASES.IDLE);
  const [extraction, setExtraction] = useState(null);
  const [image, setImage] = useState(null);
  const [result, setResult] = useState(null);
  const [extractionError, setExtractionError] = useState(null);
  const [complianceError, setComplianceError] = useState(null);

  // The id the compliance call needs. Held in a ref as well as inside
  // `extraction` so `evaluate` can read it without being re-created on every
  // render, which would re-arm any effect a caller hangs off it.
  const runIdRef = useRef(null);
  // Guards property 2. A ref rather than state: two clicks in the same tick
  // both see the old state value, and both would post.
  const evaluatingRef = useRef(false);
  const abortRef = useRef(null);
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
    evaluatingRef.current = false;
    setPhase(PHASES.IDLE);
    setExtraction(null);
    setImage(null);
    setResult(null);
    setExtractionError(null);
    setComplianceError(null);
  }, []);

  /**
   * Ask the rule engine about the reading we already have.
   *
   * Silently does nothing without a run id or while a request is in flight -
   * both are "this call should not happen", and the caller has no sensible
   * recovery for either.
   *
   * `declarations` are facts about the goods that decide whether a clause
   * governs the package. Re-evaluating with more of them stated is the
   * intended way to move a clause out of REVIEW REQUIRED, and it costs no
   * upload: the same stored reading is judged again, so the reading the user
   * is looking at cannot change underneath the new verdict.
   */
  const evaluate = useCallback(async ({ categoryCode, declarations } = {}) => {
    const runId = runIdRef.current;
    if (!runId || evaluatingRef.current) {
      return;
    }

    evaluatingRef.current = true;
    setComplianceError(null);
    setPhase(PHASES.EVALUATING);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const evaluated = await evaluateExtractionRun(runId, {
        categoryCode,
        declarations,
        signal: controller.signal,
      });
      if (!mountedRef.current) {
        return;
      }
      setResult(evaluated);
      // The result carries its own copy of the reading, mapped by the same
      // code. Adopting it keeps the reading on screen and the verdict beside it
      // provably about the same run, rather than two objects that merely
      // ought to agree.
      if (evaluated.extraction) {
        setExtraction(evaluated.extraction);
      }
      if (evaluated.image) {
        setImage(evaluated.image);
      }
      setPhase(PHASES.COMPLETE);
    } catch (cause) {
      if (!mountedRef.current) {
        return;
      }
      setComplianceError(cause);
      // Back to the reading, not to nothing: the extraction is still valid and
      // still on screen, and retrying reuses the same run.
      setPhase(PHASES.EXTRACTED);
    } finally {
      evaluatingRef.current = false;
    }
  }, []);

  /**
   * Upload the photographs of one package, read them, and evaluate the reading.
   *
   * The two steps are chained here rather than left to the caller so the run id
   * never has to leave this hook, which is what makes the "uploaded once"
   * guarantee something the UI cannot get wrong.
   *
   * Accepts one `File` or an array of them; a single photograph is the set of
   * one, and takes exactly the same path. `viewTypes` are positional, one per
   * photograph, and are never inferred from the order somebody happened to take
   * them in.
   *
   * The caller keeps the files. This hook does not hold them, so a failed
   * upload leaves the user's selection exactly where it was and the same
   * submit button resends it.
   */
  const analyse = useCallback(
    async (files, { viewTypes, categoryCode, declarations } = {}) => {
      const list = (Array.isArray(files) ? files : [files]).filter(Boolean);
      if (list.length === 0) {
        return;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      runIdRef.current = null;
      evaluatingRef.current = false;
      setPhase(PHASES.EXTRACTING);
      setExtractionError(null);
      setComplianceError(null);
      // Cleared so a previous verdict cannot sit on screen next to a new
      // photograph and be read as belonging to it.
      setResult(null);
      setExtraction(null);
      setImage(null);

      let run;
      try {
        run = await extractPackage(list, {
          viewTypes,
          signal: controller.signal,
        });
      } catch (cause) {
        if (mountedRef.current) {
          setExtractionError(cause);
          setPhase(PHASES.IDLE);
        }
        return;
      }

      if (!mountedRef.current) {
        return;
      }

      runIdRef.current = run.id;
      setExtraction(run);
      setImage(run.image);
      setPhase(PHASES.EXTRACTED);

      await evaluate({ categoryCode, declarations });
    },
    [evaluate],
  );

  return {
    phase,
    /** The reading. Present from the moment extraction succeeds. */
    extraction,
    /** The stored photograph's measured facts, including its pixel dimensions. */
    image,
    /** The verdict, findings and violations. Null until compliance succeeds. */
    result,
    extractionError,
    complianceError,
    isExtracting: phase === PHASES.EXTRACTING,
    isEvaluating: phase === PHASES.EVALUATING,
    isBusy: phase === PHASES.EXTRACTING || phase === PHASES.EVALUATING,
    analyse,
    /** Retry the verdict for the reading already held. Never re-uploads. */
    evaluate,
    reset,
  };
}
