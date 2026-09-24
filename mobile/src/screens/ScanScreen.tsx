import { useState } from 'react';
import { Image, Linking, StyleSheet, Text, TextInput, View } from 'react-native';

import { Button } from '../components/Button';
import { Callout } from '../components/Callout';
import { Card } from '../components/Card';
import { ImageTray } from '../components/ImageTray';
import { PhotoTips } from '../components/PhotoTips';
import { Screen } from '../components/Screen';
import { useAnalysis, useInspectionSelection } from '../hooks/AnalysisContext';
import { useImageSelection, type ImageSource, type SelectionIssue } from '../hooks/useImageSelection';
import type { TabScreenProps } from '../navigation/types';
import { colors, radius, spacing, typography } from '../theme';
import type { AddRejection } from '../hooks/useInspectionImages';
import { formatBytes } from '../utils/format';

/** Tallest the lead preview grows; wider phones get the full width regardless. */
const MAX_PREVIEW_HEIGHT = 360;

/**
 * The words for each way a pick can go wrong. Written for the person holding
 * the phone; the technical reason is in `SelectionIssue.kind` for a test.
 *
 * A rejection out of a multiple selection says how many were refused and how
 * many were kept, because "this photo cannot be used" would be a lie about the
 * three that came through beside it.
 */
export function describeIssue(issue: SelectionIssue): { title: string; message: string } {
  const thing = issue.source === 'camera' ? 'camera' : 'photos';
  switch (issue.kind) {
    case 'permission_denied':
      return issue.canAskAgain
        ? {
            title: `${issue.source === 'camera' ? 'Camera' : 'Photo'} access needed`,
            message: `Allow access to your ${thing} to add a photo this way.`,
          }
        : {
            title: `${issue.source === 'camera' ? 'Camera' : 'Photo'} access is turned off`,
            message: `Access to your ${thing} has been turned off for this app. You can turn it back on in your phone’s Settings.`,
          };
    case 'unavailable':
      return {
        title: 'Camera not available',
        message: 'No camera could be opened on this device. You can still choose photos from your gallery.',
      };
    case 'rejected':
      if (issue.rejectedCount > 1 || issue.acceptedCount > 0) {
        const kept =
          issue.acceptedCount > 0
            ? ` The other ${issue.acceptedCount === 1 ? 'one was' : `${issue.acceptedCount} were`} added.`
            : '';
        return {
          title: `${issue.rejectedCount} ${issue.rejectedCount === 1 ? 'photo' : 'photos'} could not be used`,
          message: `${issue.message}${kept}`,
        };
      }
      return { title: 'This photo cannot be used', message: issue.message };
    case 'error':
    default:
      return {
        title: 'Could not open that',
        message: `Something went wrong while opening your ${thing}. Please try again.`,
      };
  }
}

/** Why an add was partly or wholly refused, in the user's words. */
export function describeRejection(rejection: AddRejection, limit: number): string {
  if (rejection.kind === 'duplicate') {
    return rejection.count === 1
      ? 'That photo is already in this inspection.'
      : `${rejection.count} of those photos are already in this inspection.`;
  }
  const refused = `${rejection.refused} ${rejection.refused === 1 ? 'photo was' : 'photos were'} not added`;
  return `An inspection can hold up to ${limit} photos, so ${refused}. Remove one to make room.`;
}

/**
 * Gather the photographs of one package, then check it.
 *
 * **One inspection, several photographs.** A packaged commodity declares
 * different things on different panels - the net quantity on the back, the
 * price on a side, a batch number in small print - so this screen is built
 * around a set rather than around one picture. Adding the back of a package
 * continues the same inspection; it never starts a second one. The result is
 * one verdict about the package, computed on the server from every panel at
 * once.
 *
 * Three things here are deliberate and should survive a redesign:
 *
 * 1. **Submission is disabled with no photographs**, and the screen says why
 *    rather than leaving a dead button.
 * 2. **The count is stated on the action itself** - "Check package · 3 photos"
 *    - so nobody submits a set they did not mean to. It is the last thing read
 *    before the tap.
 * 3. **The product type is a text field, not a list**, for the reason the web
 *    client's is: no endpoint lists product categories, and a list typed into
 *    the app would be a copy of backend rows that goes stale silently. The
 *    backend validates the code and rejects an unknown one with a message this
 *    app shows. Leaving it blank is supported and honest - the result then says
 *    the product type was not known.
 */
export function ScanScreen({ navigation }: TabScreenProps<'Scan'>) {
  const analysis = useAnalysis();
  const selection = useInspectionSelection();
  const { select, issue, isPicking, clearIssue } = useImageSelection();
  const [categoryCode, setCategoryCode] = useState('');
  // Which source to add from is asked only when the user taps Add, rather than
  // by two buttons standing permanently under the tray. The tray is the
  // subject of this screen once photographs exist, and a pair of buttons
  // competing with it for attention is what pushed the tray below the fold at
  // phone width.
  const [pickerOpen, setPickerOpen] = useState(false);

  const { images, count, canAddMore, remaining, rejection } = selection;
  const lead = images[0];
  const aspectRatio = lead?.width && lead?.height ? lead.width / lead.height : 4 / 3;

  const addFrom = async (source: ImageSource) => {
    setPickerOpen(false);
    const picked = await select(source, { limit: remaining });
    if (picked.length > 0) {
      selection.add(picked);
    }
  };

  const check = () => {
    if (count === 0) {
      return;
    }
    // Not awaited: the progress screen watches the analysis as it runs.
    void analysis.analyse(images, { categoryCode: categoryCode.trim() });
    navigation.navigate('Analysis');
  };

  const described = issue ? describeIssue(issue) : null;
  const canOpenSettings = issue?.kind === 'permission_denied' && !issue.canAskAgain;

  return (
    <Screen
      testID="scan-screen"
      footer={
        <>
          <Button
            label={count > 0 ? `Check package · ${count} ${count === 1 ? 'photo' : 'photos'}` : 'Check package'}
            accessibilityLabel={
              count > 0
                ? `Check package using ${count} ${count === 1 ? 'photo' : 'photos'}`
                : 'Check package'
            }
            accessibilityHint={
              count === 0 ? 'Add at least one photo of the package first' : undefined
            }
            onPress={check}
            disabled={count === 0 || isPicking}
            testID="check-package"
          />
          <Button
            variant="text"
            label="Start over"
            accessibilityHint="Removes every photo and returns to the start"
            onPress={() => {
              selection.clear();
              // Scan is a tab now, so "the start" is the Home tab beside it -
              // not `popToTop()`, which belonged to the stack this screen used to
              // sit on and which a tab navigator cannot perform.
              navigation.navigate('Home');
            }}
            disabled={isPicking}
            testID="start-over"
          />
        </>
      }
    >
      <Text accessibilityRole="header" style={styles.title}>
        Scan a package
      </Text>
      <Text style={styles.lede}>
        Capture the front, the back, and any panel carrying a declaration. They are checked together
        as one package.
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

      {rejection ? (
        <Callout
          title="Not everything was added"
          message={describeRejection(rejection, count + remaining)}
          tone="neutral"
          testID="add-rejection"
        >
          <Button variant="text" label="Dismiss" onPress={selection.clearRejection} />
        </Callout>
      ) : null}

      {count === 0 ? (
        <Card
          title="No photos yet"
          description="At least one photo is needed. Add more if the declarations are spread across panels."
          testID="empty-selection"
        >
          <View style={styles.actions}>
            <Button
              label="Take photo"
              accessibilityHint="Opens the camera to photograph a panel of the package"
              onPress={() => {
                void addFrom('camera');
              }}
              loading={isPicking}
              testID="take-photo"
            />
            <Button
              variant="secondary"
              label="Choose from gallery"
              accessibilityHint="Opens your photos so you can pick one or more pictures of the package"
              onPress={() => {
                void addFrom('library');
              }}
              disabled={isPicking}
              testID="choose-from-gallery"
            />
          </View>
        </Card>
      ) : (
        <>
          {/*
            The first photograph, large. A row of 96 px thumbnails is enough to
            manage a set but not enough to see whether the label is in focus,
            and checking that is the one thing this screen exists for.
          */}
          <View style={styles.frame}>
            <Image
              source={{ uri: lead.uri }}
              accessible
              accessibilityLabel="Photo 1, shown large so you can check it is readable"
              style={[styles.image, { aspectRatio }]}
              resizeMode="contain"
              testID="lead-preview"
            />
          </View>
          {lead.sizeBytes !== null ? (
            <Text style={styles.meta}>{formatBytes(lead.sizeBytes)}</Text>
          ) : null}

          <Card
            title={`Photos in this inspection (${count})`}
            description={
              canAddMore
                ? 'All of these are checked together as one package. Remove any you did not mean to include.'
                : `The maximum of ${count} photos has been reached. Remove one to add another.`
            }
            testID="image-tray-card"
          >
            <ImageTray
              images={images}
              onRemove={selection.remove}
              onAdd={() => setPickerOpen(true)}
              canAddMore={canAddMore}
              busy={isPicking}
              testID="image-tray"
            />

            {pickerOpen ? (
              <View style={styles.addActions} testID="add-source-actions">
                <Button
                  label="Take photo"
                  accessibilityHint="Opens the camera to photograph another panel"
                  onPress={() => {
                    void addFrom('camera');
                  }}
                  loading={isPicking}
                  testID="take-photo"
                />
                <Button
                  variant="secondary"
                  label="Choose from gallery"
                  accessibilityHint="Opens your photos so you can pick more pictures of this package"
                  onPress={() => {
                    void addFrom('library');
                  }}
                  disabled={isPicking}
                  testID="choose-from-gallery"
                />
                <Button
                  variant="text"
                  label="Cancel"
                  onPress={() => setPickerOpen(false)}
                  testID="cancel-add"
                />
              </View>
            ) : null}
          </Card>
        </>
      )}

      <Card
        title="Product type (optional)"
        description="If you know the product category code, enter it so the right rules are applied. Leave it blank if you are not sure."
      >
        <TextInput
          value={categoryCode}
          onChangeText={setCategoryCode}
          placeholder="e.g. packaged-food"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none"
          autoCorrect={false}
          accessibilityLabel="Product category code, optional"
          style={styles.input}
          testID="category-code"
        />
      </Card>

      <Card title="Tips for a readable photo">
        <PhotoTips />
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.xs,
  },
  lede: {
    ...typography.small,
    color: colors.textSecondary,
    marginBottom: spacing.lg,
  },
  frame: {
    width: '100%',
    backgroundColor: colors.photoWell,
    borderRadius: radius.lg,
    overflow: 'hidden',
    alignItems: 'center',
  },
  image: {
    width: '100%',
    maxHeight: MAX_PREVIEW_HEIGHT,
  },
  meta: {
    ...typography.caption,
    color: colors.textMuted,
    marginTop: spacing.xs,
    marginBottom: spacing.lg,
  },
  actions: {
    gap: spacing.md,
  },
  addActions: {
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
  issueActions: {
    gap: spacing.sm,
  },
  input: {
    ...typography.body,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    minHeight: 48,
    backgroundColor: colors.surface,
  },
});
