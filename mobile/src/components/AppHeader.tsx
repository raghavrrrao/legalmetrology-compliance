import { StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { BrandMark } from './BrandMark';
import { colors, shell, spacing } from '../theme';

/**
 * The header over the five tab destinations.
 *
 * The mark, the wordmark and a line saying what the application is. **That is
 * all it holds, and the empty right-hand side is the decision, not an
 * omission.** The handoff offered an account action there; this application has
 * no accounts - no login, no profile, nothing the API scopes to a person - so an
 * avatar would be a control that opens nothing. A settings gear was the other
 * candidate and Settings is already one of the five tabs, so it would be the
 * same destination twice in one screen.
 *
 * **Height is 56 plus the top safe-area inset, and this is the only place in the
 * app that pays the top inset.** The pushed screens (Analysis, Result) use the
 * native stack's own header, which pays it too - they are never on screen at the
 * same time as this one.
 *
 * Opaque, with a hairline under it and no shadow: content scrolls *to* this
 * edge, never under it, so there is nothing for a blur to clarify and no reason
 * to recomposite a layer every frame.
 */
export function AppHeader({ testID }: { testID?: string }) {
  const insets = useSafeAreaInsets();
  return (
    <View
      style={[styles.root, { paddingTop: insets.top }]}
      testID={testID}
    >
      <View
        style={[
          styles.row,
          { paddingLeft: shell.gutter + insets.left, paddingRight: shell.gutter + insets.right },
        ]}
      >
        <BrandMark size={32} />
        <View style={styles.lockup}>
          {/*
            The wordmark is the screen's heading for a screen reader. Each tab's
            own title is a second heading inside the content, so the reading
            order is "NIRIKSHAN" then "Previous inspections" rather than one
            conflated name.
          */}
          <Text accessibilityRole="header" style={styles.wordmark}>
            NIRIKSHAN
          </Text>
          <Text style={styles.tagline} numberOfLines={1}>
            Packaged commodity inspection
          </Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  row: {
    height: shell.headerHeight,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm + 2,
  },
  lockup: {
    flex: 1,
    minWidth: 0,
  },
  wordmark: {
    fontSize: 17,
    lineHeight: 20,
    fontWeight: '700',
    letterSpacing: 0.5,
    color: colors.brandInk,
  },
  tagline: {
    fontSize: 10.5,
    lineHeight: 13,
    color: colors.textMuted,
  },
});
