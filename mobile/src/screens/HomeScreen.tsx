import { Linking, StyleSheet, Text, View } from 'react-native';

import { Button } from '../components/Button';
import { Callout } from '../components/Callout';
import { Card } from '../components/Card';
import { PhotoTips } from '../components/PhotoTips';
import { Screen } from '../components/Screen';
import { ServerStatus } from '../components/ServerStatus';
import { config } from '../config/env';
import { useApiHealth } from '../hooks/useApiHealth';
import { useImageSelection, type ImageSource } from '../hooks/useImageSelection';
import { useInspectionSelection, useStartOver } from '../hooks/AnalysisContext';
import type { RootScreenProps } from '../navigation/types';
import { colors, radius, spacing, typography } from '../theme';
import { describeIssue } from './ScanScreen';

/**
 * The words for each way a pick can go wrong.
 *
 * Written once, on the scan screen, and re-exported here rather than copied:
 * both screens can start a selection, and two sets of these sentences would
 * drift into saying different things about the same refusal.
 */
export { describeIssue };

/** The same four steps the web client names, in the same words. */
const STEPS = [
  { number: '01', title: 'Scan', text: 'Capture or upload every panel of the package that carries a declaration.' },
  { number: '02', title: 'Extract', text: 'Text recognition locates the declarations printed on the package.' },
  { number: '03', title: 'Check', text: 'Deterministic rules evaluate the requirements that apply to it.' },
  { number: '04', title: 'Review', text: 'See every finding with its evidence, and what still needs a person.' },
] as const;

export function HomeScreen({ navigation }: RootScreenProps<'Home'>) {
  const { select, issue, isPicking, clearIssue } = useImageSelection();
  const selection = useInspectionSelection();
  const startOver = useStartOver();
  // The same client, the same base URL: if this says "connected", an upload
  // that then fails is not a connectivity problem.
  const { check, ...health } = useApiHealth();

  const choose = async (source: ImageSource) => {
    const picked = await select(source);
    if (picked.length === 0) {
      return;
    }
    // Starting from here is starting a new inspection: the previous result and
    // any photographs left over from it are cleared before these are added, so
    // nothing from the last package can sit beside this one.
    startOver();
    selection.add(picked);
    navigation.navigate('Scan');
  };

  const described = issue ? describeIssue(issue) : null;
  const canOpenSettings = issue?.kind === 'permission_denied' && !issue.canAskAgain;

  return (
    <Screen testID="home-screen">
      {/*
        The hero, in the same words as the web client's. What a person needs in
        the first three seconds is what this is for and the one button that
        starts it - not the state of the analysis server, which used to sit
        directly under the title and has moved below the fold with the other
        secondary material.
      */}
      <Text style={styles.eyebrow}>
        LEGAL METROLOGY (PACKAGED COMMODITIES) RULES, 2011
      </Text>
      <Text accessibilityRole="header" style={styles.title}>
        Check a package before you trust the label.
      </Text>
      <Text style={styles.lede}>
        Photograph a packaged product, or choose pictures from your gallery. Add as many panels as
        carry a declaration — they are checked together, as one package, against the compliance
        requirements configured on the server.
      </Text>

      {described ? (
        <Callout title={described.title} message={described.message} tone="warning" testID="selection-issue">
          <View style={styles.issueActions}>
            {canOpenSettings ? (
              <Button
                variant="secondary"
                label="Open Settings"
                onPress={() => {
                  Linking.openSettings().catch(() => undefined);
                }}
              />
            ) : null}
            <Button variant="text" label="Dismiss" onPress={clearIssue} />
          </View>
        </Callout>
      ) : null}

      <View style={styles.actions}>
        <Button
          label="Take photo"
          accessibilityHint="Opens the camera to photograph a panel of the package"
          onPress={() => {
            void choose('camera');
          }}
          loading={isPicking}
          testID="take-photo"
        />
        <Button
          variant="secondary"
          label="Choose photos"
          accessibilityHint="Opens your photos so you can pick one or more pictures of the package"
          onPress={() => {
            void choose('library');
          }}
          disabled={isPicking}
          testID="choose-from-gallery"
        />
      </View>

      <Card
        title="How an inspection works"
        description="Four steps. Nothing is decided on this phone."
      >
        {STEPS.map((step) => (
          <View key={step.number} style={styles.step}>
            <Text style={styles.stepNumber}>{step.number}</Text>
            <View style={styles.stepBody}>
              <Text style={styles.stepTitle}>{step.title}</Text>
              <Text style={styles.stepText}>{step.text}</Text>
            </View>
          </View>
        ))}
      </Card>

      <Card title="Tips for a readable photo">
        <PhotoTips />
      </Card>

      {/*
        Secondary, and placed accordingly. It is genuinely useful - an upload
        that fails after this said "connected" is not a connectivity problem -
        but it is diagnostics, and diagnostics do not open a screen.
      */}
      <ServerStatus state={health} source={config.apiBaseUrlSource} onCheckAgain={check} />

      <Text style={styles.footnote}>
        The photos are sent to the analysis server, which reads them and checks them as one package.
        Nothing is analysed on this phone, and no result is produced without a connection.
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  eyebrow: {
    ...typography.overline,
    color: colors.textMuted,
    marginBottom: spacing.sm,
  },
  title: {
    ...typography.display,
    color: colors.text,
    marginBottom: spacing.md,
  },
  lede: {
    ...typography.body,
    color: colors.textSecondary,
    marginBottom: spacing.xl,
  },
  step: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: spacing.lg,
  },
  stepNumber: {
    ...typography.caption,
    fontWeight: '700',
    color: colors.primary,
    backgroundColor: colors.primarySoft,
    borderRadius: radius.sm,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    marginRight: spacing.md,
    overflow: 'hidden',
  },
  stepBody: {
    flex: 1,
  },
  stepTitle: {
    ...typography.body,
    fontWeight: '600',
    color: colors.text,
  },
  stepText: {
    ...typography.small,
    color: colors.textSecondary,
  },
  actions: {
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  issueActions: {
    gap: spacing.sm,
  },
  footnote: {
    ...typography.caption,
    color: colors.textMuted,
  },
});
