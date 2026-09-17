import { Linking, StyleSheet, Text, View } from 'react-native';

import { Button } from '../components/Button';
import { Callout } from '../components/Callout';
import { Card } from '../components/Card';
import { PhotoTips } from '../components/PhotoTips';
import { Screen } from '../components/Screen';
import { useAnalysis } from '../hooks/AnalysisContext';
import { useImageSelection, type ImageSource, type SelectionIssue } from '../hooks/useImageSelection';
import type { RootScreenProps } from '../navigation/types';
import { colors, spacing, typography } from '../theme';

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

export function HomeScreen({ navigation }: RootScreenProps<'Home'>) {
  const { select, issue, isPicking, clearIssue } = useImageSelection();
  const analysis = useAnalysis();

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
      <Text accessibilityRole="header" style={styles.title}>
        Scan a product label
      </Text>
      <Text style={styles.lede}>
        Take a photo of the package label, or choose one from your gallery, and the label will be
        checked against the Legal Metrology (Packaged Commodities) Rules, 2011.
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

      <Card title="Tips for a readable photo">
        <PhotoTips />
      </Card>

      <Text style={styles.footnote}>
        The photo is sent to the analysis server, which reads it and checks it. Nothing is analysed
        on this phone, and no result is produced without a connection.
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
