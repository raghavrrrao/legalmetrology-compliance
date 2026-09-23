import type { ReactNode } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, elevation, spacing } from '../theme';

interface ScreenProps {
  children: ReactNode;
  /** Pinned under the scrolling content - the primary actions of a screen. */
  footer?: ReactNode;
  testID?: string;
}

/**
 * The page shell: a scrolling body with a 16 px gutter at every width, and
 * an optional footer for the buttons that should not scroll away. Safe-area
 * insets are applied at the bottom and sides here; the top is the
 * navigator's header.
 */
export function Screen({ children, footer, testID }: ScreenProps) {
  const insets = useSafeAreaInsets();
  return (
    <View style={styles.root} testID={testID}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={[
          styles.content,
          { paddingLeft: spacing.lg + insets.left, paddingRight: spacing.lg + insets.right },
          !footer && { paddingBottom: spacing.xl + insets.bottom },
        ]}
        keyboardShouldPersistTaps="handled"
      >
        {children}
      </ScrollView>
      {footer ? (
        <View
          style={[
            styles.footer,
            {
              paddingLeft: spacing.lg + insets.left,
              paddingRight: spacing.lg + insets.right,
              paddingBottom: spacing.lg + insets.bottom,
            },
          ]}
        >
          {footer}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.background,
  },
  scroll: {
    flex: 1,
  },
  content: {
    paddingTop: spacing.lg,
    paddingBottom: spacing.lg,
  },
  /*
   * The pinned action bar. Content scrolls behind it, which on the web is
   * where a frosted surface earns its cost - here it is an opaque surface with
   * a hairline and a lift instead.
   *
   * Deliberately not `expo-blur`: a real backdrop blur on this bar would mean
   * a new native dependency and a continuously recomposited layer on a screen
   * the user scrolls, for a surface whose whole job is to keep one button
   * legible. The hairline and the shadow separate it just as well and cost
   * nothing per frame.
   */
  footer: {
    paddingTop: spacing.md,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: spacing.sm,
    ...elevation.raised,
  },
});
