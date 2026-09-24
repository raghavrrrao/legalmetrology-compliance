/**
 * The rule inventory the Rules screen lists, as the analysis server reports it.
 *
 * Asked once when the screen mounts - a tab stays mounted once visited, so that
 * is once per launch - and again on request after a failure. Three states and no
 * fourth: there is no "stale" or "cached" state, because the only list this app
 * has to show is the server's, and a list from anywhere else would have to be
 * told apart from it everywhere it appeared.
 *
 * Shaped like `useApiHealth`: the request is aborted on unmount, and state
 * changes only when a request that is still wanted settles.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchRuleInventory } from '../api/rules';
import type { RuleInventory } from '../types/api';
import { logError } from '../utils/errors';

export type RuleInventoryState =
  | { phase: 'loading' }
  | { phase: 'loaded'; inventory: RuleInventory }
  | { phase: 'error'; error: unknown };

export function useRuleInventory(): RuleInventoryState & { reload: () => void } {
  const [state, setState] = useState<RuleInventoryState>({ phase: 'loading' });
  const abortRef = useRef<AbortController | null>(null);

  // Starts the request; state changes only when it settles. Kept apart from
  // `reload` so the mount effect sets no state synchronously.
  const run = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    fetchRuleInventory({ signal: controller.signal }).then(
      (inventory) => {
        if (!controller.signal.aborted) {
          setState({ phase: 'loaded', inventory });
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          logError('rules', error);
          setState({ phase: 'error', error });
        }
      },
    );
  }, []);

  /** Ask again. The previous outcome is cleared first, so nothing old is on screen meanwhile. */
  const reload = useCallback(() => {
    setState({ phase: 'loading' });
    run();
  }, [run]);

  useEffect(() => {
    run();
    return () => abortRef.current?.abort();
  }, [run]);

  return { ...state, reload };
}
