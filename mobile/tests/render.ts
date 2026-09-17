/**
 * Helpers for screen tests.
 *
 * `stubNavigation` is the navigation object a screen receives, with every
 * method a spy, so a test can assert on where the screen asked to go.
 * `fakeAnalysis` builds a `LabelAnalysis` in a chosen state, so a result or
 * progress screen can be rendered directly in it without driving requests
 * through the hook first - the hook has its own tests. `PHONE_METRICS` gives
 * `SafeAreaProvider` a real frame and insets.
 */

import type { Metrics } from 'react-native-safe-area-context';

import type { LabelAnalysis } from '../src/hooks/useLabelAnalysis';

/** An iPhone-sized frame with a notch and a home indicator. */
export const PHONE_METRICS: Metrics = {
  frame: { x: 0, y: 0, width: 390, height: 844 },
  insets: { top: 47, left: 0, right: 0, bottom: 34 },
};

export function stubNavigation() {
  return {
    navigate: jest.fn(),
    replace: jest.fn(),
    goBack: jest.fn(),
    popToTop: jest.fn(),
    addListener: jest.fn((_event: string, _listener: (event: { preventDefault: () => void }) => void) => () => undefined),
    setOptions: jest.fn(),
  };
}

export type StubNavigation = ReturnType<typeof stubNavigation>;

/** A `LabelAnalysis` in a chosen state, with every action a spy. */
export function fakeAnalysis(overrides: Partial<LabelAnalysis> = {}): LabelAnalysis {
  const phase = overrides.phase ?? 'idle';
  return {
    phase,
    image: null,
    extraction: null,
    storedImage: null,
    result: null,
    extractionError: null,
    complianceError: null,
    categoryCode: '',
    isExtracting: phase === 'extracting',
    isEvaluating: phase === 'evaluating',
    isBusy: phase === 'extracting' || phase === 'evaluating',
    analyse: jest.fn(async () => undefined),
    evaluate: jest.fn(async () => undefined),
    retry: jest.fn(async () => undefined),
    reset: jest.fn(),
    ...overrides,
  };
}
