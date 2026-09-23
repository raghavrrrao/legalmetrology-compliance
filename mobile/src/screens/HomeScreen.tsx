import { Linking, StyleSheet, Text, View } from 'react-native';

import { Button } from '../components/Button';
import { Callout } from '../components/Callout';
import { Card } from '../components/Card';
import { PhotoTips } from '../components/PhotoTips';
import { Screen } from '../components/Screen';
import { ServerStatus } from '../components/ServerStatus';
import { config } from '../config/env';
import { useAnalysis } from '../hooks/AnalysisContext';
import { useApiHealth } from '../hooks/useApiHealth';
import { useImageSelection, type ImageSource, type SelectionIssue } from '../hooks/useImageSelection';
import type { RootScreenProps } from '../navigation/types';
import { colors, radius, spacing, typography } from '../theme';

/**
 * The words for each way a pick can go wrong. Written for the person holding
 * the phone; the technical reason is in `SelectionIssue.kind` for a test.
 */
export function describeIssue(issue: SelectionIssue): { title: string; message: string } {
  const thing = issue.source === 'camera' ? 'camera' : 'photos';
  switch (issue.kind) {
    case 'permission_denied':
      return issue.canAskAgain
        ? {
            title: `${issue.source === 'camera' ? 'Camera' : 'Photo'} access needed`,
            message: `Allow access to your ${thing} to scan a label this way.`,
          }
        : {
            title: `${issue.source === 'camera' ? 'Camera' : 'Photo'} access is turned off`,
            message: `Access to your ${thing} has been turned off for this app. You can turn it back on in your phone’s Settings.`,
          };
    case 'unavailable':
      return {
        title: 'Camera not available',
        message: 'No camera could be opened on this device. You can still choose a photo from your gallery.',
      };
    case 'rejected':
      return { title: 'This photo cannot be used', message: issue.message };
    case 'error':
    default:
      return {
        title: 'Could not open that',
        message: `Something went wrong while opening your ${thing}. Please try again.`,
      };
  }
}

/** The same four steps the web client names, in the same words. */
const STEPS = [
  { number: '01', title: 'Scan', text: 'Capture or upload one or more images of the package label.' },
  { number: '02', title: 'Extract', text: 'Text recognition locates the declarations printed on the package.' },
  { number: '03', title: 'Check', text: 'Deterministic rules evaluate the requirements that apply to it.' },
  { number: '04', title: 'Review', text: 'See every finding with its evidence, and what still needs a person.' },
] as const;

export function HomeScreen({ navigation }: RootScreenProps<'Home'>) {
  const { select, issue, isPicking, clearIssue } = useImageSelection();
  const analysis = useAnalysis();
  // The same client, the same base URL: if this says "connected", an upload
  // that then fails is not a connectivity problem.
  const { check, ...health } = useApiHealth();

  const choose = async (source: ImageSource) => {
    const image = await select(source);
    if (image) {
      // A new photograph means a new analysis; nothing from the last one may
      // sit beside it.
      analysis.reset();
      navigation.navigate('Preview', { image });
    }
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
        Photograph a packaged-product label, or choose one from your gallery. Its declarations are
        extracted and compared with the compliance requirements configured on the server.
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
          accessibilityHint="Opens the camera to photograph the label"
          onPress={() => {
            void choose('camera');
          }}
          loading={isPicking}
          testID="take-photo"
        />
        <Button
          variant="secondary"
          label="Choose from gallery"
          accessibilityHint="Opens your photos to pick an existing picture of the label"
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
        The photo is sent to the analysis server, which reads it and checks it. Nothing is analysed
        on this phone, and no result is produced without a connection.
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
