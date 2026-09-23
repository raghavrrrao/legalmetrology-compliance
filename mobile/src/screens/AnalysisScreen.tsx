import { useEffect } from 'react';
import { StyleSheet, Text } from 'react-native';

import { Button } from '../components/Button';
import { Callout } from '../components/Callout';
import { Card } from '../components/Card';
import { ScanPreview } from '../components/ScanPreview';
import { ProgressSteps, type ProgressStep } from '../components/ProgressSteps';
import { Screen } from '../components/Screen';
import { useAnalysis, useStartOver } from '../hooks/AnalysisContext';
import type { AnalysisPhase } from '../hooks/useLabelAnalysis';
import type { RootScreenProps } from '../navigation/types';
import { colors, spacing, typography } from '../theme';
import { describeError } from '../utils/errors';

/**
 * The steps as they really are: one per request.
 *
 * The first request uploads every photograph of the package and returns what
 * was read off them (OCR and field extraction happen inside it, on the server,
 * and the client cannot see between them); the second asks the rule engine
 * what that reading means.
 *
 * **Two steps, not five.** A longer list - "uploading", "reading", "extracting
 * declarations", "checking requirements", "preparing findings" - would look
 * more informative and would be invented: the backend performs two operations
 * this client can observe, and it reports nothing from inside either. No step
 * here is a timer, a percentage or a guess.
 *
 * `imageCount` changes only the wording of the first step, because that step
 * genuinely covers more work when there are more photographs. It never adds a
 * step per photograph: the set is read in one request and produces one
 * reading, and a step each would imply a progress signal the server does not
 * send.
 */
export function stepsForPhase(
  phase: AnalysisPhase,
  extractionFailed: boolean,
  complianceFailed: boolean,
  imageCount: number = 1,
): ProgressStep[] {
  const reading: ProgressStep = {
    key: 'reading',
    label: imageCount > 1 ? `Reading ${imageCount} photos` : 'Reading the label',
    state: 'pending',
  };
  const checking: ProgressStep = { key: 'checking', label: 'Checking the requirements', state: 'pending' };

  if (extractionFailed) {
    reading.state = 'failed';
    return [reading, checking];
  }

  switch (phase) {
    case 'extracting':
      reading.state = 'active';
      break;
    case 'extracted':
      reading.state = 'done';
      checking.state = complianceFailed ? 'failed' : 'pending';
      break;
    case 'evaluating':
      reading.state = 'done';
      checking.state = 'active';
      break;
    case 'complete':
      reading.state = 'done';
      checking.state = 'done';
      break;
    default:
      break;
  }
  return [reading, checking];
}

export function AnalysisScreen({ navigation }: RootScreenProps<'Analysis'>) {
  const analysis = useAnalysis();
  const { phase, image, images, extractionError, complianceError, isBusy, retry } = analysis;
  const startOver = useStartOver();

  useEffect(() => {
    if (phase === 'complete') {
      // Replace rather than push: going "back" from a result should not land
      // on a spinner for an analysis that has already finished.
      navigation.replace('Result');
    }
  }, [phase, navigation]);

  useEffect(() => {
    // The header has no back button, but Android's hardware back would still
    // pop this screen while a request is in flight - and then nothing would
    // be watching for the result. Hold the screen until the analysis has
    // stopped; the buttons below are the way out.
    const unsubscribe = navigation.addListener('beforeRemove', (event) => {
      if (isBusy) {
        event.preventDefault();
      }
    });
    return unsubscribe;
  }, [navigation, isBusy]);

  const error = extractionError ?? complianceError;
  const described = error ? describeError(error) : null;
  const steps = stepsForPhase(
    phase,
    Boolean(extractionError),
    Boolean(complianceError),
    images.length,
  );

  const abandon = () => {
    // Clears the photographs as well as the result. The other way out of a
    // failure is "Try again", which keeps them - see `retry`.
    startOver();
    navigation.popToTop();
  };

  if (!image && !isBusy) {
    return (
      <Screen testID="analysis-screen">
        <Callout title="Nothing to analyse" message="Add a photo of a package to begin." tone="neutral">
          <Button label="Scan a package" onPress={abandon} />
        </Callout>
      </Screen>
    );
  }

  return (
    <Screen testID="analysis-screen">
      <Text accessibilityRole="header" style={styles.title} accessibilityLiveRegion="polite">
        {described ? 'Analysis stopped' : 'Analysing label…'}
      </Text>
      <Text style={styles.lede}>
        {described
          ? 'The package could not be fully checked. Your photos have been kept.'
          : images.length > 1
            ? `All ${images.length} photos are being read and checked together, as one package, on the analysis server.`
            : 'The photo is being read and checked on the analysis server. This usually takes a few seconds.'}
      </Text>

      {/*
        The photograph under a sweep, the same treatment the web client's
        analysis frame uses. It shows what is being worked on; the steps below
        say what is being done. Neither claims progress the pipeline does not
        report.
      */}
      {image ? (
        <ScanPreview
          uri={image.uri}
          imageCount={images.length}
          scanning={isBusy}
          testID="scan-preview"
        />
      ) : null}

      <Card>
        <ProgressSteps steps={steps} />
      </Card>

      {described ? (
        <Callout title={described.title} message={described.message} tone="error" testID="analysis-error">
          {described.retryable ? (
            <Button label="Try again" onPress={() => void retry()} loading={isBusy} testID="retry" />
          ) : null}
          <Button
            variant={described.retryable ? 'text' : 'primary'}
            label="Start a new inspection"
            accessibilityHint="Discards these photos and returns to the start"
            onPress={abandon}
            disabled={isBusy}
            testID="start-over"
          />
        </Callout>
      ) : null}
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
    ...typography.body,
    color: colors.textSecondary,
    marginBottom: spacing.lg,
  },
});
