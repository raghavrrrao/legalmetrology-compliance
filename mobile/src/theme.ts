/**
 * Design tokens. One place for colour, spacing, type, radius and elevation, so
 * screens agree with each other and a contrast fix is a one-line change.
 *
 * SHARED LANGUAGE, NATIVE LAYOUT
 * ------------------------------
 * The values here are the same design system as `frontend/src/styles/index.css`
 * - the same near-white ground, the same restrained green, the same tone
 * palette, the same rhythm. They are deliberately *values* rather than a shared
 * package: a React Native app that tried to import the web's CSS would be
 * carrying a layout model it cannot run. What is shared is the vocabulary;
 * layout stays native, which is why this file has `elevation` and the web has
 * `backdrop-filter` and neither has the other.
 *
 * Any figure changed here should be changed there too. `docs/ui/design-system.md`
 * is the table both sides are checked against.
 *
 * CONTRAST
 * --------
 * Every status tone has a text colour that reads on its background at WCAG AA
 * or better - the measured ratios are in the design-system document - and
 * status is always paired with a symbol or a word, so colour is never the only
 * carrier (see `utils/status.ts`).
 *
 * The green is the accent and the accent is never a verdict. `toneColors.success`
 * is a different green from `colors.primary` on purpose: a primary button and a
 * passing check must not be the same colour, or the button starts reading as a
 * result.
 */

import { Platform } from 'react-native';

import type { Tone } from './utils/status';

export const colors = {
  /** The page ground. Near-white, not white: it gives the cards something to sit on. */
  background: '#F4F5F7',
  surface: '#FFFFFF',
  /** A recessed surface - a preview well, a disclosure body. */
  surfaceMuted: '#F6F7F9',
  surfaceSunken: '#F0F1F4',
  border: '#E4E5EA',
  borderStrong: '#D3D5DC',

  /** 17.0 : 1 on white. */
  text: '#1C1C1E',
  /** 6.4 : 1 on white. */
  textSecondary: '#5B5F66',
  /** 5.0 : 1 on white - still AA for body text, not only for large. */
  textMuted: '#6E7076',

  /** The one accent: primary actions, the active step, a focused control. */
  primary: '#0E7C50',
  primaryPressed: '#0A6640',
  /** The tint a secondary or text button takes while pressed. */
  primarySoft: '#E8F4EE',
  primarySofter: '#F3FAF6',
  onPrimary: '#FFFFFF',
  focus: '#0E7C50',

  /** The backdrop behind a photograph, so a light label still has an edge. */
  photoWell: '#26282D',
} as const;

export const toneColors: Readonly<
  Record<Tone, { background: string; text: string; border: string }>
> = {
  success: { background: '#E7F4EC', text: '#10693A', border: '#B6DDC5' },
  warning: { background: '#FDF4E3', text: '#8A5300', border: '#EED6A6' },
  error: { background: '#FDECEA', text: '#B3261E', border: '#F2C4C0' },
  review: { background: '#E9EFF6', text: '#3A4C63', border: '#C6D4E4' },
  muted: { background: '#F0F1F4', text: '#56585E', border: '#DCDDE2' },
  neutral: { background: '#EEEFF2', text: '#4A4C52', border: '#DCDDE2' },
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

/**
 * Large but controlled. 18 is the card figure; going further turns a data
 * surface into a toy, and a 24 is reserved for the two elements that are meant
 * to read as sheets - the verdict and the photo well.
 */
export const radius = {
  xs: 6,
  sm: 10,
  md: 14,
  lg: 18,
  xl: 24,
  pill: 999,
} as const;

/**
 * Elevation, as both platforms express it. A hairline border does most of the
 * work; the shadow is deliberately faint, because a heavy drop shadow on a
 * white card is the fastest way to make an interface look like 2014.
 *
 * `elevation` is Android's only lever and it also draws a shadow, so the two
 * are set together and tuned to look the same rather than to be the same
 * numbers.
 */
export const elevation = {
  card: Platform.select({
    ios: {
      shadowColor: '#14181C',
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.06,
      shadowRadius: 3,
    },
    android: { elevation: 1 },
    default: {},
  }),
  raised: Platform.select({
    ios: {
      shadowColor: '#14181C',
      shadowOffset: { width: 0, height: 6 },
      shadowOpacity: 0.1,
      shadowRadius: 16,
    },
    android: { elevation: 4 },
    default: {},
  }),
} as const;

/**
 * Type scale. Negative tracking on the larger sizes is what gives the system
 * font its iOS set; body and below stay at zero, where tightening costs
 * legibility at small sizes on a phone.
 */
export const typography = {
  display: { fontSize: 30, fontWeight: '700' as const, lineHeight: 36, letterSpacing: -0.6 },
  title: { fontSize: 24, fontWeight: '700' as const, lineHeight: 30, letterSpacing: -0.45 },
  heading: { fontSize: 18, fontWeight: '600' as const, lineHeight: 24, letterSpacing: -0.25 },
  body: { fontSize: 16, lineHeight: 22 },
  small: { fontSize: 14, lineHeight: 20 },
  caption: { fontSize: 13, lineHeight: 18 },
  /** Eyebrows and column headings: small, spaced, upper case at the call site. */
  overline: { fontSize: 11, fontWeight: '700' as const, lineHeight: 16, letterSpacing: 0.6 },
} as const;

/** Minimum touch target, per both platforms' accessibility guidance. */
export const MIN_TOUCH_TARGET = 48;
