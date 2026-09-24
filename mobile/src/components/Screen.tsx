import { useContext, type ReactNode } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import { BottomTabBarHeightContext } from '@react-navigation/bottom-tabs';
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
 * an optional footer for the buttons that should not scroll away.
 *
 * SAFE AREAS: WHO PAYS THE BOTTOM INSET
 * -------------------------------------
 * The side insets are always paid here, and the top never is - that is the
 * header's, on both navigators.
 *
 * The bottom one has two answers, because this component is used from both
 * navigators. Under the tab bar (Home, Scan, Inspections, Rules, Settings) **the
 * tab bar pays it**: it is an opaque bar that occupies layout, its own height
 * already includes the inset, and the screen's box ends at its top edge. Adding
 * the inset here as well would leave a 34 pt gap on an iPhone and a 16 pt one on
 * an Android gesture bar, above a bar that has already cleared them - visible as
 * a footer floating away from the tab bar, and as dead space under the last card.
 *
 * On a pushed screen (Analysis, Result) there is no tab bar, so this component
 * pays it exactly as it did before the tabs existed.
 *
 * `BottomTabBarHeightContext` is read rather than `useBottomTabBarHeight()`
 * because the hook throws outside a tab navigator and half the callers are
 * outside one. `undefined` from the context *is* the answer to the question
 * being asked - "is there a bar below me?" - so it is not a fallback.
 *
 * This holds only while the bar occupies layout. If it is ever made absolute or
 * translucent, content would scroll under it and the fix is to reserve
 * `tabBarHeight` here, not to bring the raw inset back.
 */
export function Screen({ children, footer, testID }: ScreenProps) {
  const insets = useSafeAreaInsets();
  const tabBarHeight = useContext(BottomTabBarHeightContext);
  const bottomInset = tabBarHeight === undefined ? insets.bottom : 0;
  return (
    <View style={styles.root} testID={testID}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={[
          styles.content,
          { paddingLeft: spacing.lg + insets.left, paddingRight: spacing.lg + insets.right },
          !footer && { paddingBottom: spacing.xl + bottomInset },
        ]}
        keyboardShouldPersistTaps="handled"
        // Fixed rather than derived from `testID`: `Screen.test.tsx` asserts the
        // padding on these two boxes, and which of them pays the bottom inset is
        // the whole subject of that file.
        testID="screen-scroll"
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
              paddingBottom: spacing.lg + bottomInset,
            },
          ]}
          testID="screen-footer"
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
