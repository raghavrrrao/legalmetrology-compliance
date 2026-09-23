import type { ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { colors, elevation, radius, spacing, typography } from '../theme';

interface CardProps {
  title?: string;
  /** A sentence under the title explaining what the card shows. */
  description?: string;
  children: ReactNode;
  testID?: string;
}

/** A titled surface. The title is a heading for screen readers. */
export function Card({ title, description, children, testID }: CardProps) {
  return (
    <View style={styles.card} testID={testID}>
      {title ? (
        <Text accessibilityRole="header" style={styles.title}>
          {title}
        </Text>
      ) : null}
      {description ? <Text style={styles.description}>{description}</Text> : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    marginBottom: spacing.lg,
    ...elevation.card,
  },
  title: {
    ...typography.heading,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  description: {
    ...typography.small,
    color: colors.textSecondary,
    marginBottom: spacing.md,
  },
});
