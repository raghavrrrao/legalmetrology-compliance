/**
 * Helpers for screen tests.
 *
 * `stubNavigation` is the navigation object a screen receives, with every
 * method a spy, so a test can assert on where the screen asked to go.
 * `fakeAnalysis` builds a `LabelAnalysis` in a chosen state and
 * `fakeSelection` an `InspectionImages`, so a scan, progress or result screen
 * can be rendered directly in it without driving requests through the hooks
 * first - the hooks have their own tests. `PHONE_METRICS` gives
 * `SafeAreaProvider` a real frame and insets.
 */

import type { Metrics } from 'react-native-safe-area-context';

import type { InspectionImages } from '../src/hooks/useInspectionImages';
import type { LabelAnalysis } from '../src/hooks/useLabelAnalysis';
import { MAX_INSPECTION_IMAGES } from '../src/config/env';

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

/**
 * A `LabelAnalysis` in a chosen state, with every action a spy.
 *
 * `image` is derived from `images` unless a test overrides it, the same way
 * the real hook derives it - so a test cannot accidentally set up a state the
 * hook could never produce, with a primary photograph that is not in the set.
 */
export function fakeAnalysis(overrides: Partial<LabelAnalysis> = {}): LabelAnalysis {
  const phase = overrides.phase ?? 'idle';
  const images = overrides.images ?? (overrides.image ? [overrides.image] : []);
  return {
    phase,
    image: images[0] ?? null,
    images,
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
    // After the spread, so a test that passes only `images` still gets a
    // consistent primary rather than the `overrides.image` default above.
    ...(overrides.image === undefined ? { image: images[0] ?? null } : {}),
  };
}

/** An `InspectionImages` holding a chosen set, with every action a spy. */
export function fakeSelection(overrides: Partial<InspectionImages> = {}): InspectionImages {
  const images = overrides.images ?? [];
  return {
    images,
    count: images.length,
    canAddMore: images.length < MAX_INSPECTION_IMAGES,
    remaining: Math.max(0, MAX_INSPECTION_IMAGES - images.length),
    rejection: null,
    add: jest.fn(() => ({ added: 0, rejection: null })),
    remove: jest.fn(),
    replaceAll: jest.fn(),
    clear: jest.fn(),
    clearRejection: jest.fn(),
    ...overrides,
  };
}
