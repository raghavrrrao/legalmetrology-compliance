/**
 * The progress screen: what the user sees while the backend works, and when
 * it fails.
 */

import { fireEvent, render, screen } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AnalysisScreen, stepsForPhase } from './AnalysisScreen';
import { selectedImage } from '../../tests/fixtures';
import { fakeAnalysis, PHONE_METRICS, stubNavigation } from '../../tests/render';
import { ApiError } from '../api/client';

const mockUseAnalysis = jest.fn();
jest.mock('../hooks/AnalysisContext', () => ({
  useAnalysis: () => mockUseAnalysis(),
}));

async function renderAnalysis(overrides: Parameters<typeof fakeAnalysis>[0] = {}) {
  const analysis = fakeAnalysis({ image: selectedImage(), ...overrides });
  mockUseAnalysis.mockReturnValue(analysis);
  const navigation = stubNavigation();
  await render(
    <SafeAreaProvider initialMetrics={PHONE_METRICS}>
      <AnalysisScreen navigation={navigation as never} route={{ key: 'Analysis', name: 'Analysis' } as never} />
    </SafeAreaProvider>,
  );
  return { analysis, navigation };
}

describe('stepsForPhase', () => {
  it('reflects the real request in flight, never a guess', () => {
    expect(stepsForPhase('extracting', false, false).map((step) => step.state)).toEqual(['active', 'pending']);
    expect(stepsForPhase('extracted', false, false).map((step) => step.state)).toEqual(['done', 'pending']);
    expect(stepsForPhase('evaluating', false, false).map((step) => step.state)).toEqual(['done', 'active']);
    expect(stepsForPhase('complete', false, false).map((step) => step.state)).toEqual(['done', 'done']);
  });

  it('marks the step that failed', () => {
    expect(stepsForPhase('idle', true, false).map((step) => step.state)).toEqual(['failed', 'pending']);
    expect(stepsForPhase('extracted', false, true).map((step) => step.state)).toEqual(['done', 'failed']);
  });
});

describe('AnalysisScreen', () => {
  it('tells the user the label is being read', async () => {
    await renderAnalysis({ phase: 'extracting' });

    expect(screen.getByText('Analysing label…')).toBeOnTheScreen();
    expect(screen.getByTestId('step-reading-active')).toBeOnTheScreen();
    expect(screen.getByTestId('step-checking-pending')).toBeOnTheScreen();
    expect(screen.queryByTestId('analysis-error')).toBeNull();
  });

  it('moves the progress on when the requirements are being checked', async () => {
    await renderAnalysis({ phase: 'evaluating' });

    expect(screen.getByTestId('step-reading-done')).toBeOnTheScreen();
    expect(screen.getByTestId('step-checking-active')).toBeOnTheScreen();
  });

  it('goes to the result as soon as the analysis completes', async () => {
    const { navigation } = await renderAnalysis({ phase: 'complete' });
    expect(navigation.replace).toHaveBeenCalledWith('Result');
  });

  it('shows the offline message with a retry when the server could not be reached', async () => {
    const { analysis } = await renderAnalysis({
      phase: 'idle',
      extractionError: new ApiError('Unable to connect to the analysis server.', { status: 0, code: 'network_error' }),
    });

    expect(screen.getByText('Analysis stopped')).toBeOnTheScreen();
    expect(screen.getByTestId('analysis-error')).toHaveTextContent('Unable to connect to the analysis server.', { exact: false });
    expect(screen.getByTestId('step-reading-failed')).toBeOnTheScreen();

    await fireEvent.press(screen.getByTestId('retry'));
    expect(analysis.retry).toHaveBeenCalled();
  });

  it('shows the backend\'s reason for a rejected photo, without a retry', async () => {
    const { analysis, navigation } = await renderAnalysis({
      phase: 'idle',
      extractionError: new ApiError('The submitted data was not valid.', {
        status: 400,
        code: 'validation_error',
        details: { image: ['The file could not be read as an image.'] },
      }),
    });

    expect(screen.getByTestId('analysis-error')).toHaveTextContent('The file could not be read as an image.', { exact: false });
    expect(screen.queryByTestId('retry')).toBeNull();

    await fireEvent.press(screen.getByTestId('start-over'));
    expect(analysis.reset).toHaveBeenCalled();
    expect(navigation.popToTop).toHaveBeenCalled();
  });

  it.each([
    [401, /sign in/i],
    [403, /permission/i],
    [404, /not found/i],
    [413, /too large/i],
    [429, /wait/i],
    [500, /server/i],
  ])('has a message for an HTTP %s', async (status, pattern) => {
    await renderAnalysis({ phase: 'idle', extractionError: new ApiError('x', { status, code: 'e' }) });
    expect(screen.getByTestId('analysis-error')).toHaveTextContent(pattern);
  });

  it('keeps the reading step done when only the verdict failed', async () => {
    await renderAnalysis({
      phase: 'extracted',
      complianceError: new ApiError('Server error', { status: 500, code: 'unexpected_response' }),
    });

    expect(screen.getByTestId('step-reading-done')).toBeOnTheScreen();
    expect(screen.getByTestId('step-checking-failed')).toBeOnTheScreen();
    expect(screen.getByTestId('retry')).toBeOnTheScreen();
  });

  it('holds the screen against a back navigation while a request is in flight', async () => {
    const { navigation } = await renderAnalysis({ phase: 'extracting' });

    const listener = navigation.addListener.mock.calls.find(([name]) => name === 'beforeRemove')?.[1];
    expect(listener).toBeDefined();

    const event = { preventDefault: jest.fn() };
    listener?.(event);
    expect(event.preventDefault).toHaveBeenCalled();
  });

  it('lets the screen go once the analysis has stopped', async () => {
    const { navigation } = await renderAnalysis({ phase: 'idle', extractionError: new ApiError('x', { status: 500, code: 'e' }) });

    const listener = navigation.addListener.mock.calls.find(([name]) => name === 'beforeRemove')?.[1];
    const event = { preventDefault: jest.fn() };
    listener?.(event);
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it('handles being opened with nothing to analyse', async () => {
    const { navigation } = await renderAnalysis({ image: null, phase: 'idle' });

    expect(screen.getByText('Nothing to analyse')).toBeOnTheScreen();
    await fireEvent.press(screen.getByText('Scan a label'));
    expect(navigation.popToTop).toHaveBeenCalled();
  });
});
