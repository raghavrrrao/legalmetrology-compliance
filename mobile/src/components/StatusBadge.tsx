import { StyleSheet, Text, View } from 'react-native';

import { radius, spacing, toneColors, typography } from '../theme';
import { SYMBOL_BY_TONE, type Tone } from '../utils/status';

interface StatusBadgeProps {
  label: string;
  tone?: Tone;
  /** Larger variant for the verdict banner. */
  size?: 'small' | 'large';
  testID?: string;
}

/**
 * A coloured label for a status the backend decided.
 *
 * `tone` is chosen by the caller from `utils/status.ts` rather than derived
 * here, so a verdict and a finding status can share the component without it
 * knowing either vocabulary. The symbol is part of the text, so a screen
 * reader and a colour-blind user both get the same information as the colour.
 */
export function StatusBadge({ label, tone = 'neutral', size = 'small', testID }: StatusBadgeProps) {
  const palette = toneColors[tone];
  return (
    <View
      accessible
      accessibilityRole="text"
      accessibilityLabel={`Status: ${label}`}
      testID={testID}
      style={[
        styles.badge,
        size === 'large' && styles.badgeLarge,
        { backgroundColor: palette.background, borderColor: palette.border },
      ]}
    >
      <Text style={[styles.symbol, size === 'large' && styles.textLarge, { color: palette.text }]}>
        {SYMBOL_BY_TONE[tone]}
      </Text>
      <Text style={[styles.label, size === 'large' && styles.textLarge, { color: palette.text }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
    borderRadius: radius.pill,
    borderWidth: 1,
    maxWidth: '100%',
  },
  badgeLarge: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
  },
  symbol: {
    ...typography.small,
    fontWeight: '700',
    marginRight: spacing.xs,
  },
  label: {
    ...typography.small,
    fontWeight: '600',
    flexShrink: 1,
  },
  textLarge: {
    ...typography.heading,
  },
});
