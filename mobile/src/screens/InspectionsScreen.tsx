import { StyleSheet, Text, View } from 'react-native';

import { Button } from '../components/Button';
import { Screen } from '../components/Screen';
import { TabBarIcon } from '../components/TabBarIcon';
import type { TabScreenProps } from '../navigation/types';
import { colors, elevation, radius, spacing, typography } from '../theme';

/**
 * Previous inspections.
 *
 * WHY THIS IS AN EMPTY STATE AND NOT A LIST
 * -----------------------------------------
 * The handoff includes a populated list - rows with a thumbnail, a name, a date
 * and a verdict badge. Those rows are a layout specimen whose fields are written
 * `[PACKAGE NAME]` and `[DATE]`, and they are not implemented as data here,
 * because nothing this client can ask would fill them honestly:
 *
 * - **There is no on-device history.** Nothing persists an inspection to the
 *   phone. `AnalysisProvider` holds the current one in memory and is cleared by
 *   "start over"; there is no store to read a past one from.
 * - **The server's list cannot answer "mine" for this app.**
 *   `GET /api/v1/compliance/` does exist and does list stored checks, and the web
 *   client uses it. It scopes rows to the caller - and this app has no caller.
 *   There is no login, so every request is anonymous, and
 *   `CallerScopedCheckQuerysetMixin` scopes anonymous requests to *all* the
 *   anonymous ones: a shared pool, as its own docstring says. Drawing that under
 *   the heading "Previous inspections" would show one person a stranger's
 *   uploads. On a deployment where `DEMO_PUBLIC_ANALYSIS_API` is off - the
 *   default - there is no anonymous pool to read at all.
 *
 * So the list is not wired up, and the screen says what is true instead of
 * showing an empty list that implies rows will appear on their own. The two ways
 * to make it real are an account system, or binding an anonymous check to its
 * session - the second is noted as unlanded work in the mixin's docstring. Both
 * are backend changes and neither belongs in a navigation redesign.
 *
 * The copy is the part that had to change from the handoff, which read "Every
 * inspection you complete is listed here, newest first." That is a promise this
 * build does not keep.
 */
export function InspectionsScreen({ navigation }: TabScreenProps<'Inspections'>) {
  return (
    <Screen testID="inspections-screen">
      <Text accessibilityRole="header" style={styles.title}>
        Previous inspections
      </Text>
      <Text style={styles.lede}>
        A record of finished inspections is not kept on this phone.
      </Text>

      <View style={styles.empty} testID="inspections-empty">
        <View style={styles.glyph}>
          <TabBarIcon name="history" color={colors.textMuted} size={26} />
        </View>
        <Text accessibilityRole="header" style={styles.emptyTitle}>
          Nothing to show here yet
        </Text>
        <Text style={styles.emptyBody}>
          Each inspection’s verdict, findings and photographs are shown when it finishes. Leaving
          that result — or starting another package — discards it, and this build has nowhere to look
          it up again afterwards.
        </Text>
        <Button
          label="Scan a package"
          accessibilityHint="Opens the scan tab so you can photograph a package"
          onPress={() => navigation.navigate('Scan')}
          testID="scan-from-inspections"
        />
      </View>

      <Text style={styles.footnote} testID="inspections-footnote">
        The analysis server does store every check it performs. Listing them per person needs a way
        to tell one person from another, which this app does not have — it signs in to nothing, so
        the server cannot tell its requests apart from anyone else’s.
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  lede: {
    ...typography.body,
    color: colors.textSecondary,
    marginBottom: spacing.xl,
  },
  empty: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.lg,
    alignItems: 'center',
    marginBottom: spacing.lg,
    ...elevation.card,
  },
  glyph: {
    width: 56,
    height: 56,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSunken,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.lg,
  },
  emptyTitle: {
    ...typography.heading,
    color: colors.text,
    marginBottom: spacing.sm,
    textAlign: 'center',
  },
  emptyBody: {
    ...typography.small,
    color: colors.textSecondary,
    textAlign: 'center',
    marginBottom: spacing.xl,
  },
  footnote: {
    ...typography.caption,
    color: colors.textMuted,
  },
});
