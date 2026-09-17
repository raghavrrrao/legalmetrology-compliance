import { StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '../theme';

interface KeyValueProps {
  label: string;
  value: string;
  /** Render the value in a monospace face - ids, raw OCR text. */
  mono?: boolean;
  testID?: string;
}

/** A label and its value, stacked so neither is truncated on a narrow screen. */
export function KeyValue({ label, value, mono = false, testID }: KeyValueProps) {
  return (
    <View style={styles.row} accessible accessibilityLabel={`${label}: ${value}`} testID={testID}>
      <Text style={styles.label}>{label}</Text>
      <Text style={[styles.value, mono && styles.mono]} selectable>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    marginBottom: spacing.md,
  },
  label: {
    ...typography.caption,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginBottom: 2,
  },
  value: {
    ...typography.body,
    color: colors.text,
  },
  mono: {
    fontFamily: 'monospace',
    fontSize: 14,
    lineHeight: 20,
  },
});
