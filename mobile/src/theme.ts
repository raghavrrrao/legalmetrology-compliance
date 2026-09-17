/**
 * Design tokens. One place for colour, spacing and type so screens agree with
 * each other and a contrast fix is a one-line change.
 *
 * Every status tone has a text colour that reads on its background at WCAG AA
 * or better, and status is always paired with a symbol or a word - colour is
 * never the only carrier (see `utils/status.ts`).
 */

import type { Tone } from './utils/status';

export const colors = {
  background: '#F6F7F9',
  surface: '#FFFFFF',
  border: '#D5D9E0',
  text: '#15202B',
  textSecondary: '#4B5563',
  textMuted: '#6B7280',
  primary: '#1F4E9C',
  primaryPressed: '#173D7A',
  onPrimary: '#FFFFFF',
  focus: '#1F4E9C',
} as const;

export const toneColors: Readonly<Record<Tone, { background: string; text: string; border: string }>> = {
  success: { background: '#E3F3E8', text: '#14532D', border: '#86C79B' },
  warning: { background: '#FFF3DF', text: '#7C3E00', border: '#F0B565' },
  error: { background: '#FDE8E8', text: '#8A1C1C', border: '#F09A9A' },
  review: { background: '#E7EEFA', text: '#1E3F7A', border: '#9DB6E6' },
  muted: { background: '#EEF0F3', text: '#374151', border: '#C4C9D1' },
  neutral: { background: '#EEF0F3', text: '#1F2937', border: '#C4C9D1' },
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 6,
  md: 10,
  lg: 14,
} as const;

export const typography = {
  title: { fontSize: 24, fontWeight: '700' as const, lineHeight: 30 },
  heading: { fontSize: 18, fontWeight: '600' as const, lineHeight: 24 },
  body: { fontSize: 16, lineHeight: 22 },
  small: { fontSize: 14, lineHeight: 20 },
  caption: { fontSize: 13, lineHeight: 18 },
} as const;

/** Minimum touch target, per both platforms' accessibility guidance. */
export const MIN_TOUCH_TARGET = 48;
