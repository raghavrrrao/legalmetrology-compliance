import { ActivityIndicator, Pressable, StyleSheet, Text, type StyleProp, type ViewStyle } from 'react-native';

import { colors, elevation, MIN_TOUCH_TARGET, radius, spacing, typography } from '../theme';

interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'text';
  disabled?: boolean;
  /** Shows a spinner and disables the button; the label stays for context. */
  loading?: boolean;
  /** Spoken by a screen reader in place of the label, when the label alone is ambiguous. */
  accessibilityLabel?: string;
  accessibilityHint?: string;
  testID?: string;
  style?: StyleProp<ViewStyle>;
}

/**
 * The one button. Full width, at least 48 px tall, with a visible pressed
 * state and an explicit disabled state that a screen reader also announces.
 */
export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled = false,
  loading = false,
  accessibilityLabel,
  accessibilityHint,
  testID,
  style,
}: ButtonProps) {
  const inactive = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: inactive, busy: loading }}
      disabled={inactive}
      onPress={onPress}
      testID={testID}
      style={({ pressed }) => [
        styles.base,
        styles[variant],
        pressed && !inactive && pressedStyles[variant],
        inactive && styles.disabled,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator
          color={variant === 'primary' ? colors.onAction : colors.action}
          style={styles.spinner}
          accessibilityElementsHidden
        />
      ) : null}
      <Text style={[styles.label, labelStyles[variant]]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: MIN_TOUCH_TARGET + 4,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    alignSelf: 'stretch',
  },
  primary: {
    backgroundColor: colors.action,
    ...elevation.card,
  },
  secondary: {
    backgroundColor: colors.surface,
    borderWidth: 1.5,
    borderColor: colors.action,
  },
  text: {
    backgroundColor: 'transparent',
  },
  disabled: {
    opacity: 0.55,
  },
  label: {
    ...typography.body,
    fontWeight: '600',
    textAlign: 'center',
  },
  spinner: {
    marginRight: spacing.sm,
  },
});

const pressedStyles = StyleSheet.create({
  primary: { backgroundColor: colors.actionPressed },
  secondary: { backgroundColor: colors.actionSoft },
  text: { backgroundColor: colors.actionSoft },
});

const labelStyles = StyleSheet.create({
  primary: { color: colors.onAction },
  secondary: { color: colors.action },
  text: { color: colors.action },
});
