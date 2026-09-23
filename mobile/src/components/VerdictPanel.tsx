import type { ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { colors, elevation, radius, spacing, toneColors, typography } from '../theme';
import type { Tone } from '../utils/status';

interface VerdictPanelProps {
  /** Chosen by the caller from `utils/status.ts`, never derived here. */
  tone: Tone;
  children: ReactNode;
  testID?: string;
}

/**
 * The tinted surface the verdict sits on - the strongest element on the result
 * screen, and the web `VerdictBanner`'s counterpart.
 *
 * It is a *surface*, not a verdict. `tone` arrives already chosen by
 * `toneForResult`, which is the one place a backend status becomes an
 * appearance; this component never looks at the result value and never maps a
 * verdict to a colour. An unrecognised status tones to `neutral` and is drawn
 * neutrally, which is the honest treatment for it.
 *
 * The tint is never the only signal. The `StatusBadge` inside carries the
 * verdict in words and with its own symbol, and the engine's summary sits
 * directly beneath - so the panel reads the same in greyscale, under forced
 * colours, and to a screen reader.
 */
export function VerdictPanel({ tone, children, testID }: VerdictPanelProps) {
  const palette = toneColors[tone];
  return (
    <View
      testID={testID}
      style={[styles.panel, { backgroundColor: palette.background, borderColor: palette.border }]}
    >
      <Text style={styles.eyebrow}>AUTOMATED COMPLIANCE CHECK</Text>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    borderRadius: radius.xl,
    borderWidth: 1,
    padding: spacing.lg,
    marginBottom: spacing.lg,
    ...elevation.raised,
  },
  eyebrow: {
    ...typography.overline,
    color: colors.textSecondary,
    marginBottom: spacing.md,
  },
});
