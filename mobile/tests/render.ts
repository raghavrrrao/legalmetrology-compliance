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

/**
 * The widths the shell is required to hold, with a plausible inset set for each.
 *
 * 360 is the one that matters: it is the narrowest Android phone still in wide
 * use and the width at which five labelled tabs either fit or do not. 768 is a
 * tablet - `app.json` sets `supportsTablet`, so the bar has to survive it even
 * though the handoff only drew phones.
 *
 * The insets are the platform's own conventions rather than measurements: a
 * notched iPhone's 47/34, an Android gesture bar's 24/16, a tablet's 24/20.
 * Nothing asserts the numbers; they are here so a test at 360 exercises a
 * different inset pair from one at 390 and cannot pass by accident.
 */
export const SHELL_WIDTHS = [360, 390, 430, 768] as const;

export function metricsFor(width: (typeof SHELL_WIDTHS)[number]): Metrics {
  const insets =
    width === 360
      ? { top: 24, left: 0, right: 0, bottom: 16 }
      : width === 768
        ? { top: 24, left: 0, right: 0, bottom: 20 }
        : { top: 47, left: 0, right: 0, bottom: 34 };
  return { frame: { x: 0, y: 0, width, height: width >= 768 ? 1024 : 844 }, insets };
}

/**
 * The navigation object a screen receives, with every method a spy.
 *
 * Deliberately **no `popToTop`**. The five destinations are bottom tabs now, and
 * a tab navigator has no `popToTop` - offering one here would let a screen pass
 * its test by calling a method the real prop does not have. Getting back to the
 * beginning is `navigate('MainTabs', { screen: 'Home' })` from a pushed screen
 * and `navigate('Home')` from a sibling tab; both are `navigate`.
 */
export function stubNavigation() {
  return {
    navigate: jest.fn(),
    replace: jest.fn(),
    goBack: jest.fn(),
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
