import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, toneColors, typography } from '../theme';

export type StepState = 'pending' | 'active' | 'done' | 'failed';

export interface ProgressStep {
  key: string;
  label: string;
  state: StepState;
}

const SYMBOL: Record<StepState, string> = {
  pending: '○',
  active: '',
  done: '✓',
  failed: '✕',
};

const SPOKEN: Record<StepState, string> = {
  pending: 'not started',
  active: 'in progress',
  done: 'done',
  failed: 'failed',
};

/**
 * The steps of an analysis and where it is.
 *
 * Each step is one real request or one real outcome - never an animated
 * percentage. The active step shows a spinner; the others show a symbol and
 * are described in words for a screen reader.
 */
export function ProgressSteps({ steps }: { steps: ProgressStep[] }) {
  return (
    <View accessibilityRole="list">
      {steps.map((step) => (
        <View
          key={step.key}
          accessible
          accessibilityLabel={`${step.label}, ${SPOKEN[step.state]}`}
          style={styles.row}
          testID={`step-${step.key}-${step.state}`}
        >
          <View style={styles.marker}>
            {step.state === 'active' ? (
              <ActivityIndicator size="small" color={colors.action} />
            ) : (
              <Text style={[styles.symbol, symbolStyle(step.state)]}>{SYMBOL[step.state]}</Text>
            )}
          </View>
          <Text style={[styles.label, step.state === 'pending' && styles.labelPending]}>{step.label}</Text>
        </View>
      ))}
    </View>
  );
}

function symbolStyle(state: StepState) {
  switch (state) {
    case 'done':
      return { color: toneColors.success.text };
    case 'failed':
      return { color: toneColors.error.text };
    default:
      return { color: colors.textMuted };
  }
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
  },
  marker: {
    width: 28,
    alignItems: 'center',
    marginRight: spacing.sm,
  },
  symbol: {
    ...typography.body,
    fontWeight: '700',
  },
  label: {
    ...typography.body,
    color: colors.text,
    flex: 1,
  },
  labelPending: {
    color: colors.textMuted,
  },
});
