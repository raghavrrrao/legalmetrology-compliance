/**
 * The scan screen: composing the set of photographs that make one inspection.
 *
 * What is asserted here is the contract between a person and a submission -
 * that they can see exactly which photographs will be checked, add to them,
 * take one away, and cannot submit by accident. The picker is mocked at the
 * expo-image-picker boundary (tests/setup.ts), so permission handling and
 * validation run for real; the selection hook is stubbed per test so a state
 * can be set up directly rather than reached through six taps.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import * as ImagePicker from 'expo-image-picker';
import { Linking, Platform } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { describeRejection, ScanScreen } from './ScanScreen';
import { cameraPermission, libraryPermission, selectedImages } from '../../tests/fixtures';
import { fakeAnalysis, fakeSelection, PHONE_METRICS, stubNavigation } from '../../tests/render';
import { MAX_INSPECTION_IMAGES } from '../config/env';
import type { InspectionImages } from '../hooks/useInspectionImages';

const mockUseAnalysis = jest.fn();
const mockUseSelection = jest.fn();
jest.mock('../hooks/AnalysisContext', () => ({
  useAnalysis: () => mockUseAnalysis(),
  useInspectionSelection: () => mockUseSelection(),
  useStartOver: () => jest.fn(),
}));

const picker = ImagePicker as jest.Mocked<typeof ImagePicker>;
const granted = cameraPermission(true);

const asset = {
  uri: 'file:///cache/ImagePicker/new.jpg',
  fileName: 'new.jpg',
  mimeType: 'image/jpeg',
  fileSize: 123456,
  width: 3000,
  height: 4000,
};

/** Cleanups a single test registered; run after each one. */
const afterEachRestore: (() => void)[] = [];

afterEach(() => {
  while (afterEachRestore.length > 0) {
    afterEachRestore.pop()?.();
  }
});

async function renderScan(selectionOverrides: Partial<InspectionImages> = {}) {
  const analysis = fakeAnalysis();
  const selection = fakeSelection(selectionOverrides);
  mockUseAnalysis.mockReturnValue(analysis);
  mockUseSelection.mockReturnValue(selection);
  const navigation = stubNavigation();
  await render(
    <SafeAreaProvider initialMetrics={PHONE_METRICS}>
      <ScanScreen navigation={navigation as never} route={{ key: 'Scan', name: 'Scan' } as never} />
    </SafeAreaProvider>,
  );
  return { analysis, selection, navigation };
}

describe('ScanScreen', () => {
  // --- what is in the inspection ------------------------------------------

  it('shows every photo of the set as a numbered thumbnail', async () => {
    await renderScan({ images: selectedImages(3) });

    expect(screen.getByTestId('image-tray')).toBeOnTheScreen();
    expect(screen.getByTestId('image-tile-0')).toBeOnTheScreen();
    expect(screen.getByTestId('image-tile-1')).toBeOnTheScreen();
    expect(screen.getByTestId('image-tile-2')).toBeOnTheScreen();
    expect(screen.getByText('Photos in this inspection (3)')).toBeOnTheScreen();
  });

  it('says on the action itself how many photos will be submitted', async () => {
    await renderScan({ images: selectedImages(3) });

    // The last thing read before the tap, so a set nobody meant to send is
    // caught before it is sent rather than explained afterwards.
    expect(screen.getByTestId('check-package')).toHaveTextContent('Check package · 3 photos');
  });

  it('says one photo in the singular', async () => {
    await renderScan({ images: selectedImages(1) });

    expect(screen.getByTestId('check-package')).toHaveTextContent('Check package · 1 photo');
  });

  it('shows the first photo large so the user can see whether it is readable', async () => {
    await renderScan({ images: selectedImages(2) });

    expect(screen.getByTestId('lead-preview')).toBeOnTheScreen();
  });

  // --- the empty state ------------------------------------------------------

  it('disables submission and explains why when there are no photos', async () => {
    await renderScan({ images: [] });

    expect(screen.getByTestId('empty-selection')).toBeOnTheScreen();
    expect(screen.getByText(/At least one photo is needed/)).toBeOnTheScreen();
    expect(screen.getByTestId('check-package')).toBeDisabled();
  });

  it('does not start an analysis when there is nothing to submit', async () => {
    const { analysis, navigation } = await renderScan({ images: [] });

    await fireEvent.press(screen.getByTestId('check-package'));

    expect(analysis.analyse).not.toHaveBeenCalled();
    expect(navigation.navigate).not.toHaveBeenCalled();
  });

  // --- submitting -----------------------------------------------------------

  it('submits the whole set as one inspection', async () => {
    const images = selectedImages(3);
    const { analysis, navigation } = await renderScan({ images });

    await fireEvent.press(screen.getByTestId('check-package'));

    // One call with three photographs - never three calls.
    expect(analysis.analyse).toHaveBeenCalledTimes(1);
    expect(analysis.analyse).toHaveBeenCalledWith(images, { categoryCode: '' });
    expect(navigation.navigate).toHaveBeenCalledWith('Analysis');
  });

  it('sends the product type a person typed, trimmed', async () => {
    const images = selectedImages(2);
    const { analysis } = await renderScan({ images });

    await fireEvent.changeText(screen.getByTestId('category-code'), '  packaged-food  ');
    await fireEvent.press(screen.getByTestId('check-package'));

    expect(analysis.analyse).toHaveBeenCalledWith(images, { categoryCode: 'packaged-food' });
  });

  // --- adding ---------------------------------------------------------------

  it('adds a photo to the existing set rather than starting a new inspection', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockResolvedValue({ canceled: false, assets: [asset] });
    const { selection, navigation } = await renderScan({ images: selectedImages(2) });

    await fireEvent.press(screen.getByTestId('add-image'));
    await fireEvent.press(screen.getByTestId('take-photo'));

    await waitFor(() => expect(selection.add).toHaveBeenCalled());
    expect(selection.add).toHaveBeenCalledWith([
      expect.objectContaining({ uri: asset.uri, name: 'new.jpg' }),
    ]);
    // Adding is not navigating: the user stays here, with the set in front of
    // them.
    expect(navigation.navigate).not.toHaveBeenCalled();
  });

  it('adds several photos from one gallery visit', async () => {
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue(libraryPermission(true));
    picker.launchImageLibraryAsync.mockResolvedValue({
      canceled: false,
      assets: [
        { ...asset, uri: 'file:///b.jpg', fileName: 'b.jpg' },
        { ...asset, uri: 'file:///c.jpg', fileName: 'c.jpg' },
      ],
    });
    const { selection } = await renderScan({ images: selectedImages(1) });

    await fireEvent.press(screen.getByTestId('add-image'));
    await fireEvent.press(screen.getByTestId('choose-from-gallery'));

    await waitFor(() => expect(selection.add).toHaveBeenCalled());
    expect((selection.add as jest.Mock).mock.calls[0][0]).toHaveLength(2);
  });

  it('asks the picker only for the room the inspection has left', async () => {
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue(libraryPermission(true));
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: true, assets: null });
    await renderScan({ images: selectedImages(4), remaining: 2 });

    await fireEvent.press(screen.getByTestId('add-image'));
    await fireEvent.press(screen.getByTestId('choose-from-gallery'));

    // Stopping the user inside the picker beats refusing their extras after.
    await waitFor(() => expect(picker.launchImageLibraryAsync).toHaveBeenCalled());
    expect(picker.launchImageLibraryAsync).toHaveBeenCalledWith(
      expect.objectContaining({ selectionLimit: 2 }),
    );
  });

  it('disables adding once the set is full', async () => {
    await renderScan({
      images: selectedImages(MAX_INSPECTION_IMAGES),
      canAddMore: false,
      remaining: 0,
    });

    expect(screen.getByTestId('add-image')).toBeDisabled();
    expect(screen.getByText(/maximum of 6 photos has been reached/)).toBeOnTheScreen();
  });

  it('still allows submission when the set is full', async () => {
    await renderScan({
      images: selectedImages(MAX_INSPECTION_IMAGES),
      canAddMore: false,
      remaining: 0,
    });

    expect(screen.getByTestId('check-package')).not.toBeDisabled();
  });

  // --- removing -------------------------------------------------------------

  it('removes the photo whose control was pressed', async () => {
    const { selection } = await renderScan({ images: selectedImages(3) });

    await fireEvent.press(screen.getByTestId('remove-image-1'));

    expect(selection.remove).toHaveBeenCalledWith(1);
  });

  it('gives every remove control a label naming its photo', async () => {
    await renderScan({ images: selectedImages(3) });

    // So a screen-reader user can remove the third photo without finding out
    // which one "remove" means by pressing it.
    expect(screen.getByLabelText('Remove photo 1')).toBeOnTheScreen();
    expect(screen.getByLabelText('Remove photo 2')).toBeOnTheScreen();
    expect(screen.getByLabelText('Remove photo 3')).toBeOnTheScreen();
  });

  it('labels each thumbnail with its position in the set', async () => {
    await renderScan({ images: selectedImages(2) });

    expect(screen.getByLabelText('Photo 1 of 2')).toBeOnTheScreen();
    expect(screen.getByLabelText('Photo 2 of 2')).toBeOnTheScreen();
  });

  it('labels the action for a screen reader with the number of photos', async () => {
    await renderScan({ images: selectedImages(3) });

    expect(screen.getByLabelText('Check package using 3 photos')).toBeOnTheScreen();
  });

  // --- refusals -------------------------------------------------------------

  it('says when a photo is already in the inspection', async () => {
    await renderScan({
      images: selectedImages(2),
      rejection: { kind: 'duplicate', count: 1 },
    });

    expect(await screen.findByTestId('add-rejection')).toHaveTextContent(
      'That photo is already in this inspection.',
      { exact: false },
    );
  });

  it('says how many were refused when the set would overflow', async () => {
    await renderScan({
      images: selectedImages(6),
      remaining: 0,
      canAddMore: false,
      rejection: { kind: 'full', added: 1, refused: 2 },
    });

    expect(await screen.findByTestId('add-rejection')).toHaveTextContent('2 photos were not added', {
      exact: false,
    });
  });

  it('lets a refusal be dismissed', async () => {
    const { selection } = await renderScan({
      images: selectedImages(2),
      rejection: { kind: 'duplicate', count: 1 },
    });

    await fireEvent.press(screen.getAllByText('Dismiss')[0]);

    expect(selection.clearRejection).toHaveBeenCalled();
  });

  // --- permissions ----------------------------------------------------------

  it('explains a refused camera permission and adds nothing', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(cameraPermission(false, true));
    const { selection } = await renderScan({ images: [] });

    await fireEvent.press(screen.getByTestId('take-photo'));

    expect(await screen.findByTestId('selection-issue')).toHaveTextContent('Camera access needed', {
      exact: false,
    });
    expect(selection.add).not.toHaveBeenCalled();
    expect(picker.launchCameraAsync).not.toHaveBeenCalled();
  });

  it('offers Settings when the camera permission can no longer be asked for', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(cameraPermission(false, false));
    const openSettings = jest.spyOn(Linking, 'openSettings').mockResolvedValue(undefined);
    await renderScan({ images: [] });

    await fireEvent.press(screen.getByTestId('take-photo'));

    expect(await screen.findByTestId('selection-issue')).toHaveTextContent('turned off', {
      exact: false,
    });
    await fireEvent.press(screen.getByText('Open Settings'));
    expect(openSettings).toHaveBeenCalled();
  });

  it('explains a refused gallery permission and keeps the existing photos', async () => {
    // Android, because that is the only platform where the library permission
    // is asked for at all - iOS 14+ and Android 13+ use a system picker that
    // needs none, which `imagePicker.ts` documents and its own tests cover.
    const originalOS = Platform.OS;
    Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
    afterEachRestore.push(() =>
      Object.defineProperty(Platform, 'OS', { value: originalOS, configurable: true }),
    );
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue(libraryPermission(false, true));
    const { selection } = await renderScan({ images: selectedImages(2) });

    await fireEvent.press(screen.getByTestId('add-image'));
    await fireEvent.press(screen.getByTestId('choose-from-gallery'));

    expect(await screen.findByTestId('selection-issue')).toHaveTextContent('Photo access needed', {
      exact: false,
    });
    expect(selection.add).not.toHaveBeenCalled();
    expect(selection.clear).not.toHaveBeenCalled();
    // The two the user already had are still on screen.
    expect(screen.getByTestId('image-tile-1')).toBeOnTheScreen();
  });

  it('adds nothing and says nothing when the camera is dismissed', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockResolvedValue({ canceled: true, assets: null });
    const { selection } = await renderScan({ images: selectedImages(1) });

    await fireEvent.press(screen.getByTestId('add-image'));
    await fireEvent.press(screen.getByTestId('take-photo'));

    await waitFor(() => expect(picker.launchCameraAsync).toHaveBeenCalled());
    expect(selection.add).not.toHaveBeenCalled();
    expect(screen.queryByTestId('selection-issue')).toBeNull();
  });
});

describe('describeRejection', () => {
  it('names a single duplicate without a count', () => {
    expect(describeRejection({ kind: 'duplicate', count: 1 }, 6)).toBe(
      'That photo is already in this inspection.',
    );
  });

  it('counts several duplicates', () => {
    expect(describeRejection({ kind: 'duplicate', count: 3 }, 6)).toContain('3 of those photos');
  });

  it('says the limit and what to do about it', () => {
    const message = describeRejection({ kind: 'full', added: 0, refused: 2 }, 6);

    expect(message).toContain('up to 6 photos');
    expect(message).toContain('Remove one to make room');
  });
});
