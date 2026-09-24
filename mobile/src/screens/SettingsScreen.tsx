import Constants from 'expo-constants';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { Screen } from '../components/Screen';
import { ServerStatus } from '../components/ServerStatus';
import { config, MAX_INSPECTION_IMAGES, MAX_UPLOAD_SIZE_MB } from '../config/env';
import { RULE_COUNTS } from '../data/lmpcRules';
import { useApiHealth } from '../hooks/useApiHealth';
import type { TabScreenProps } from '../navigation/types';
import { colors, elevation, MIN_TOUCH_TARGET, radius, spacing, typography } from '../theme';

/**
 * Settings.
 *
 * **Everything here is something that already exists.** The screen is a reading
 * of this build's own configuration plus the two controls the app genuinely has:
 * re-check the server, and open the operating system's permission screen.
 *
 * What the handoff sketched and this does not have, each for the same reason -
 * the thing does not exist, so a control for it would be a control that lies:
 * no account or profile (nothing to sign in to), no notification preferences
 * (nothing notifies), no cloud sync (nothing syncs), no privacy toggles (there is
 * nothing to opt out of), no theme switch (the app is light-only, per
 * `app.json`'s `userInterfaceStyle`), and no editable server address - the base
 * URL is fixed at build time from `EXPO_PUBLIC_API_BASE_URL`, so a text field
 * here would accept input and change nothing.
 *
 * The values are therefore read-only, and the two that are limits say so plainly:
 * they mirror the backend's own and the backend stays the authority, which is the
 * comment `config/env.ts` already carries for both.
 */
export function SettingsScreen({ navigation }: TabScreenProps<'Settings'>) {
  const { check, ...health } = useApiHealth();
  // `expoConfig` is null in a bare build and in tests; the version is shown only
  // when it is actually known rather than guessed at or hard-coded here.
  const version = Constants.expoConfig?.version ?? null;

  return (
    <Screen testID="settings-screen">
      <Text accessibilityRole="header" style={styles.title}>
        Settings
      </Text>

      <Section label="ANALYSIS SERVER">
        {/*
          The existing component, unchanged: it already shows the address, says
          whether the address was configured or guessed, and offers "Check again".
          A second status line here would be a second thing to keep in step.
        */}
        <ServerStatus state={health} source={config.apiBaseUrlSource} onCheckAgain={check} />
      </Section>

      <Section label="INSPECTION LIMITS">
        <View style={styles.card}>
          <Row label="Photographs per inspection" value={String(MAX_INSPECTION_IMAGES)} />
          <Divider />
          <Row label="Largest photograph" value={`${MAX_UPLOAD_SIZE_MB} MB`} />
        </View>
        <Text style={styles.note}>
          Both mirror the analysis server’s own limits so a set that is too large is refused here
          rather than after the upload. The server decides either way.
        </Text>
      </Section>

      <Section label="PERMISSIONS">
        <View style={styles.card}>
          <Row
            label="Camera and photos"
            value="Open system settings"
            onPress={() => {
              Linking.openSettings().catch(() => undefined);
            }}
            testID="open-system-settings"
          />
        </View>
        <Text style={styles.note}>
          Access is asked for the first time you take or choose a photo. This app cannot change the
          answer, only your phone’s settings can.
        </Text>
      </Section>

      <Section label="ABOUT">
        <View style={styles.card}>
          {version ? (
            <>
              <Row label="App version" value={version} testID="app-version" />
              <Divider />
            </>
          ) : null}
          <Row
            label="Rules this server checks"
            value={`${RULE_COUNTS.evaluated} of ${RULE_COUNTS.recorded}`}
            onPress={() => navigation.navigate('Rules')}
            testID="open-rules"
          />
        </View>
      </Section>

      <Text style={styles.footnote} testID="settings-footnote">
        Photographs are sent to the analysis server, which reads them and checks them as one
        package. Nothing is analysed on this phone, and no result is produced without a connection.
      </Text>
    </Screen>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text accessibilityRole="header" style={styles.sectionLabel}>
        {label}
      </Text>
      {children}
    </View>
  );
}

/**
 * One row. A `<Pressable>` when it goes somewhere and a plain `<View>` when it
 * does not, so a screen reader never announces a read-only value as a button.
 */
function Row({
  label,
  value,
  onPress,
  testID,
}: {
  label: string;
  value: string;
  onPress?: () => void;
  testID?: string;
}) {
  const body = (
    <>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
      {onPress ? <Text style={styles.chevron}>›</Text> : null}
    </>
  );

  if (!onPress) {
    return (
      <View style={styles.row} accessible accessibilityLabel={`${label}: ${value}`} testID={testID}>
        {body}
      </View>
    );
  }
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${label}. ${value}`}
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
      testID={testID}
    >
      {body}
    </Pressable>
  );
}

function Divider() {
  return <View style={styles.divider} />;
}

const styles = StyleSheet.create({
  title: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.lg,
  },
  section: {
    marginBottom: spacing.xl,
  },
  sectionLabel: {
    ...typography.overline,
    color: colors.textMuted,
    marginBottom: spacing.sm,
    marginLeft: 2,
  },
  card: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    overflow: 'hidden',
    ...elevation.card,
  },
  row: {
    minHeight: MIN_TOUCH_TARGET + 4,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  rowPressed: {
    backgroundColor: colors.surfaceMuted,
  },
  /* Inset from the left so it reads as separating rows inside one card, rather
     than as cutting the card in two. */
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginLeft: spacing.lg,
  },
  rowLabel: {
    ...typography.body,
    color: colors.text,
    flexGrow: 1,
    flexShrink: 1,
  },
  rowValue: {
    ...typography.small,
    color: colors.textSecondary,
    flexShrink: 0,
  },
  chevron: {
    ...typography.body,
    color: colors.borderStrong,
    flexShrink: 0,
  },
  note: {
    ...typography.caption,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
  footnote: {
    ...typography.caption,
    color: colors.textMuted,
  },
});
