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
 * ONE RULE ABOUT COLOUR
 * ---------------------
 * **Blue is anything you can press or are currently on. Green is a state the
 * server reported.** `colors.action` carries every control and the selected tab;
 * `toneColors` carry verdicts, findings and server health. Nothing in this file
 * decides a status - see `utils/status.ts`.
 *
 * This supersedes an earlier arrangement in which the accent was itself a green
 * (`colors.primary`, `#0E7C50`) held one shade apart from `toneColors.success`
 * so that a primary button would not read as a passing check. Two greens a
 * shade apart is a distinction that survives a design review and not a phone
 * screen in sunlight; moving actions to blue removes the collision instead of
 * managing it. `colors.primary` is gone entirely - see the note where it was.
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

  /**
   * The accent. Every control, link and the selected tab.
   *
   * 6.1 : 1 on white, and white on it is the same 6.1 : 1 - so it is legible
   * both as text on a light surface and as the ground under a white label,
   * which is what a fill and an outline variant of one button need.
   */
  action: '#1B5FC1',
  /** 8.3 : 1 on white. The fill while pressed. */
  actionPressed: '#154C9B',
  /** The selected tab's pill and the tint a secondary button takes while pressed. `action` on it is 5.3 : 1. */
  actionSoft: '#E8EFFA',
  /** A ground only - a dashed drop target. Never carries text. */
  actionSofter: '#F3F7FD',
  onAction: '#FFFFFF',
  focus: '#1B5FC1',

  /**
   * The brand mark's tile and the wordmark. 14.2 : 1 on white.
   *
   * **Not a control colour.** It is deliberately close to `text` and would read
   * as a disabled button; the only things wearing it are the mark and the word
   * NIRIKSHAN.
   */
  brandInk: '#17253B',

  /*
   * There is deliberately no `primary`, `primarySoft` or `onPrimary` any more.
   *
   * They were the green accent, and every one of their callers turned out to be
   * a control: the button fills, the tray's add tile, the result screen's
   * disclosure toggle, two spinners. Each moved to `action`, which left five
   * tokens with no callers. They are deleted rather than kept "for
   * compatibility", because a green named `primary` sitting beside a blue named
   * `action` is how a button ends up green again six months from now. The web
   * client still has `--colour-primary` green - that divergence is recorded in
   * `docs/ui/design-system.md` and is not resolved here.
   */

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

/**
 * The application shell: the header over the tabs and the tab bar under them.
 *
 * Heights here are the *content* box. Each bar adds its own safe-area inset on
 * top - the header the top inset, the tab bar the bottom one - and nothing else
 * in the app adds either again. `components/Screen.tsx` is where that is
 * enforced for the scrolling body between them.
 *
 * The tab bar's figures are what make five labelled destinations fit a 360 pt
 * phone. At that width each item is (360 - 8) / 5 = 70.4 pt and the label box
 * inside it 64.4 pt, against about 47 pt for "Settings", the longest of the
 * five. They are stated rather than left to flexbox so that a later sixth
 * destination has to confront the arithmetic instead of silently truncating.
 */
export const shell = {
  headerHeight: 56,
  tabBarHeight: 56,
  /** Horizontal padding inside the bars, matching the content gutter. */
  gutter: spacing.lg,
  /** The pill behind a selected tab's icon. */
  tabPill: { width: 44, height: 26 },
  tabIcon: 22,
} as const;

/** A tab label. Small, never truncated, and one line at every supported width. */
export const tabLabelType = {
  fontSize: 11,
  lineHeight: 14,
  letterSpacing: 0.1,
} as const;
