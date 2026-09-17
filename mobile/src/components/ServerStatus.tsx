import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, MIN_TOUCH_TARGET, spacing, toneColors, typography } from '../theme';
import type { HealthCheckState } from '../hooks/useApiHealth';
import { SYMBOL_BY_TONE } from '../utils/status';

interface ServerStatusProps {
  state: HealthCheckState;
  /** Where the address came from, so a guessed one is labelled as guessed. */
  source: 'configured' | 'development-default';
  onCheckAgain: () => void;
}

/**
 * One line saying whether the analysis server answered, and at which address.
 *
 * The address is always shown. "Unreachable" on its own would send a
 * developer looking at the phone's signal when the app is pointed at a laptop
 * that is not running the backend; the host name is what makes the
 * difference visible. It is public configuration and carries no secret.
 */
export function ServerStatus({ state, source, onCheckAgain }: ServerStatusProps) {
  const host = state.target.host;
  const guessed = source === 'development-default' ? ' (development default)' : '';

  let tone: keyof typeof toneColors = 'neutral';
  let label: string;
  let detail: string;
  switch (state.phase) {
    case 'checking':
      label = 'Checking the analysis server…';
      detail = `${host}${guessed}`;
      break;
    case 'ok': {
      const engine = state.health.extractionEngine;
      tone = 'success';
      label = 'Analysis server connected';
      detail = `${host}${guessed}${engine.name ? ` · ${engine.name} ${engine.version ?? ''}`.trimEnd() : ''}`;
      break;
    }
    case 'unreachable':
    default:
      tone = 'warning';
      label = 'Analysis server unreachable';
      detail = `${host}${guessed}. Scans will not work until it can be reached.`;
      break;
  }

  const palette = toneColors[tone];

  return (
    <View
      accessible
      accessibilityRole="text"
      accessibilityLabel={`${label}. ${detail}`}
      accessibilityLiveRegion="polite"
      style={[styles.row, { backgroundColor: palette.background, borderColor: palette.border }]}
      testID={`server-status-${state.phase}`}
    >
      <View style={styles.marker}>
        {state.phase === 'checking' ? (
          <ActivityIndicator size="small" color={colors.primary} />
        ) : (
          <Text style={[styles.symbol, { color: palette.text }]}>{SYMBOL_BY_TONE[tone]}</Text>
        )}
      </View>
      <View style={styles.text}>
        <Text style={[styles.label, { color: palette.text }]}>{label}</Text>
        <Text style={[styles.detail, { color: palette.text }]} testID="server-status-detail">
          {detail}
        </Text>
      </View>
      {state.phase === 'unreachable' ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Check the analysis server again"
          onPress={onCheckAgain}
          style={styles.retry}
          testID="server-status-retry"
        >
          <Text style={[styles.retryText, { color: palette.text }]}>Check again</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.lg,
    minHeight: MIN_TOUCH_TARGET,
  },
  marker: {
    width: 24,
    alignItems: 'center',
    marginRight: spacing.sm,
  },
  symbol: {
    ...typography.body,
    fontWeight: '700',
  },
  text: {
    flex: 1,
  },
  label: {
    ...typography.small,
    fontWeight: '600',
  },
  detail: {
    ...typography.caption,
  },
  retry: {
    minHeight: MIN_TOUCH_TARGET,
    justifyContent: 'center',
    paddingHorizontal: spacing.sm,
  },
  retryText: {
    ...typography.small,
    fontWeight: '700',
  },
});
