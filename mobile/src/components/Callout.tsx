import type { ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { radius, spacing, toneColors, typography } from '../theme';
import { SYMBOL_BY_TONE, type Tone } from '../utils/status';

interface CalloutProps {
  title: string;
  message: string;
  tone?: Tone;
  /** Buttons or links rendered under the message. */
  children?: ReactNode;
  testID?: string;
}

/**
 * A message the user needs to read - an error, a warning, a note.
 *
 * Announced as an alert when it is an error, so a screen reader user hears it
 * without having to find it. The symbol duplicates the colour.
 */
export function Callout({ title, message, tone = 'neutral', children, testID }: CalloutProps) {
  const palette = toneColors[tone];
  const isAlert = tone === 'error' || tone === 'warning';
  return (
    <View
      accessibilityRole={isAlert ? 'alert' : undefined}
      accessibilityLiveRegion={isAlert ? 'assertive' : 'polite'}
      testID={testID}
      style={[styles.callout, { backgroundColor: palette.background, borderColor: palette.border }]}
    >
      <View style={styles.header}>
        <Text style={[styles.symbol, { color: palette.text }]}>{SYMBOL_BY_TONE[tone]}</Text>
        <Text style={[styles.title, { color: palette.text }]}>{title}</Text>
      </View>
      <Text style={[styles.message, { color: palette.text }]}>{message}</Text>
      {children ? <View style={styles.actions}>{children}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  callout: {
    borderRadius: radius.md,
    borderWidth: 1,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: spacing.xs,
  },
  symbol: {
    ...typography.body,
    fontWeight: '700',
    marginRight: spacing.sm,
  },
  title: {
    ...typography.body,
    fontWeight: '700',
    flex: 1,
  },
  message: {
    ...typography.small,
  },
  actions: {
    marginTop: spacing.md,
  },
});
