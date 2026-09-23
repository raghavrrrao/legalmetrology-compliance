/**
 * The home screen: the two ways to start an inspection, and every way that can end.
 *
 * The picker module is mocked at the expo-image-picker boundary
 * (tests/setup.ts), so the app's own permission handling, validation and
 * navigation all run for real.
 *
 * Home no longer carries the photograph to the next screen. It seeds the
 * inspection's image set - which lives in the provider, so that adding a
 * second panel and retrying a failed upload both work - and then navigates.
 * The assertions below are on what it put in the set, not on a route param.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import * as ImagePicker from 'expo-image-picker';
import { Linking } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { HomeScreen } from './HomeScreen';
import { cameraPermission, healthBody, jsonResponse, libraryPermission, routedFetch } from '../../tests/fixtures';
import { fakeSelection, PHONE_METRICS, stubNavigation } from '../../tests/render';
import { config } from '../config/env';

const mockUseSelection = jest.fn();
const mockStartOver = jest.fn();
jest.mock('../hooks/AnalysisContext', () => ({
  useInspectionSelection: () => mockUseSelection(),
  useStartOver: () => mockStartOver,
}));

const picker = ImagePicker as jest.Mocked<typeof ImagePicker>;
const granted = cameraPermission(true);

const asset = {
  uri: 'file:///cache/ImagePicker/abc.jpg',
  fileName: 'abc.jpg',
  mimeType: 'image/jpeg',
  fileSize: 123456,
  width: 3000,
  height: 4000,
};

beforeEach(() => {
  (globalThis as unknown as { fetch: unknown }).fetch = routedFetch();
  jest.spyOn(console, 'info').mockImplementation(() => undefined);
});

async function renderHome() {
  const selection = fakeSelection();
  mockUseSelection.mockReturnValue(selection);
  const navigation = stubNavigation();
  await render(
    <SafeAreaProvider initialMetrics={PHONE_METRICS}>
      <HomeScreen navigation={navigation as never} route={{ key: 'Home', name: 'Home' } as never} />
    </SafeAreaProvider>,
  );
  return { selection, navigation };
}

describe('HomeScreen', () => {
  it('checks the analysis server through the API client and shows the host it used', async () => {
    await renderHome();

    const status = await screen.findByTestId('server-status-ok');
    expect(status).toHaveTextContent('Analysis server connected', { exact: false });
    expect(screen.getByTestId('server-status-detail')).toHaveTextContent(new URL(config.apiBaseUrl).host, { exact: false });
    expect(screen.getByTestId('server-status-detail')).toHaveTextContent('tesseract 0.3.0', { exact: false });

    const fetchStub = globalThis.fetch as unknown as ReturnType<typeof routedFetch>;
    expect(fetchStub.calls[0].url).toBe(`${config.apiBaseUrl}health/`);
  });

  it('says the server is unreachable, at which address, and lets the user check again', async () => {
    const fetchStub = routedFetch({ health: new TypeError('Network request failed') });
    (globalThis as unknown as { fetch: unknown }).fetch = fetchStub;
    await renderHome();

    const status = await screen.findByTestId('server-status-unreachable');
    expect(status).toHaveTextContent('Analysis server unreachable', { exact: false });
    expect(screen.getByTestId('server-status-detail')).toHaveTextContent(new URL(config.apiBaseUrl).host, { exact: false });

    (globalThis as unknown as { fetch: unknown }).fetch = routedFetch({ health: jsonResponse(healthBody()) });
    await fireEvent.press(screen.getByTestId('server-status-retry'));

    await screen.findByTestId('server-status-ok');
  });

  it('offers the camera and the gallery, and some advice', async () => {
    await renderHome();

    expect(screen.getByRole('button', { name: 'Take photo' })).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Choose photos' })).toBeOnTheScreen();
    expect(screen.getByText(/Avoid glare/)).toBeOnTheScreen();
    expect(screen.getByText(/Nothing is analysed on this phone/)).toBeOnTheScreen();
  });

  it('seeds the inspection with the validated photo and opens the scan screen', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockResolvedValue({ canceled: false, assets: [asset] });
    const { selection, navigation } = await renderHome();

    await fireEvent.press(screen.getByTestId('take-photo'));

    await waitFor(() => expect(navigation.navigate).toHaveBeenCalled());
    // Starting from Home is starting a new inspection: the last result and any
    // photographs left over from it go first.
    expect(mockStartOver).toHaveBeenCalled();
    expect(selection.add).toHaveBeenCalledWith([
      { uri: asset.uri, name: 'abc.jpg', type: 'image/jpeg', sizeBytes: 123456, width: 3000, height: 4000 },
    ]);
    expect(navigation.navigate).toHaveBeenCalledWith('Scan');
  });

  it('seeds every photo of a multiple gallery selection, in order', async () => {
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue(libraryPermission(true));
    picker.launchImageLibraryAsync.mockResolvedValue({
      canceled: false,
      assets: [
        { ...asset, uri: 'file:///front.jpg', fileName: 'front.jpg' },
        { ...asset, uri: 'file:///back.jpg', fileName: 'back.jpg' },
        { ...asset, uri: 'file:///side.jpg', fileName: 'side.jpg' },
      ],
    });
    const { selection, navigation } = await renderHome();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));

    await waitFor(() => expect(navigation.navigate).toHaveBeenCalled());
    // One inspection of three panels, not three inspections - and the order is
    // the order the user chose, because it becomes the position on each.
    expect(selection.add).toHaveBeenCalledTimes(1);
    expect((selection.add as jest.Mock).mock.calls[0][0].map((one: { name: string }) => one.name)).toEqual([
      'front.jpg',
      'back.jpg',
      'side.jpg',
    ]);
    expect(navigation.navigate).toHaveBeenCalledWith('Scan');
  });

  it('normalises a gallery pick with no filename before adding it', async () => {
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue(libraryPermission(true));
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: [{ ...asset, fileName: null, mimeType: 'image/png' }] });
    const { selection } = await renderHome();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));

    await waitFor(() => expect(selection.add).toHaveBeenCalled());
    expect(selection.add).toHaveBeenCalledWith([
      expect.objectContaining({ name: 'label.png', type: 'image/png' }),
    ]);
  });

  it('stays put, with no message, when the camera is dismissed', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockResolvedValue({ canceled: true, assets: null });
    const { navigation } = await renderHome();

    await fireEvent.press(screen.getByTestId('take-photo'));

    await waitFor(() => expect(picker.launchCameraAsync).toHaveBeenCalled());
    expect(navigation.navigate).not.toHaveBeenCalled();
    expect(screen.queryByTestId('selection-issue')).toBeNull();
  });

  it('stays put, with no message, when the gallery is dismissed', async () => {
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue(libraryPermission(true));
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: true, assets: null });
    const { navigation } = await renderHome();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));

    await waitFor(() => expect(picker.launchImageLibraryAsync).toHaveBeenCalled());
    expect(navigation.navigate).not.toHaveBeenCalled();
    expect(screen.queryByTestId('selection-issue')).toBeNull();
  });

  it('explains a refused camera permission', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(cameraPermission(false, true));
    await renderHome();

    await fireEvent.press(screen.getByTestId('take-photo'));

    const issue = await screen.findByTestId('selection-issue');
    expect(issue).toHaveTextContent('Camera access needed', { exact: false });
    expect(screen.queryByText('Open Settings')).toBeNull();
    expect(picker.launchCameraAsync).not.toHaveBeenCalled();
  });

  it('offers Settings when the camera permission can no longer be asked for', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(cameraPermission(false, false));
    const openSettings = jest.spyOn(Linking, 'openSettings').mockResolvedValue(undefined);
    await renderHome();

    await fireEvent.press(screen.getByTestId('take-photo'));

    const issue = await screen.findByTestId('selection-issue');
    expect(issue).toHaveTextContent('turned off', { exact: false });
    await fireEvent.press(screen.getByText('Open Settings'));
    expect(openSettings).toHaveBeenCalled();
  });

  it('says when no camera is available and points at the gallery', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockRejectedValue(Object.assign(new Error('no activity'), { code: 'ERR_MISSING_ACTIVITY' }));
    await renderHome();

    await fireEvent.press(screen.getByTestId('take-photo'));

    expect(await screen.findByTestId('selection-issue')).toHaveTextContent('Camera not available', { exact: false });
  });

  it('rejects an unsupported format before uploading', async () => {
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue(libraryPermission(true));
    picker.launchImageLibraryAsync.mockResolvedValue({
      canceled: false,
      assets: [{ ...asset, uri: 'file:///x.heic', fileName: 'IMG_1.HEIC', mimeType: 'image/heic' }],
    });
    const { navigation } = await renderHome();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));

    expect(await screen.findByTestId('selection-issue')).toHaveTextContent('JPEG, PNG or WebP', { exact: false });
    expect(navigation.navigate).not.toHaveBeenCalled();
  });

  it('keeps the acceptable photos when one of a multiple selection is rejected', async () => {
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue(libraryPermission(true));
    picker.launchImageLibraryAsync.mockResolvedValue({
      canceled: false,
      assets: [
        { ...asset, uri: 'file:///front.jpg', fileName: 'front.jpg' },
        { ...asset, uri: 'file:///x.heic', fileName: 'IMG_1.HEIC', mimeType: 'image/heic' },
      ],
    });
    const { selection, navigation } = await renderHome();

    await fireEvent.press(screen.getByTestId('choose-from-gallery'));

    // Throwing the whole selection away would make the user repeat a choice
    // that was mostly fine, over a file format they cannot change.
    await waitFor(() => expect(selection.add).toHaveBeenCalled());
    expect((selection.add as jest.Mock).mock.calls[0][0]).toHaveLength(1);
    expect(navigation.navigate).toHaveBeenCalledWith('Scan');
    expect(await screen.findByTestId('selection-issue')).toHaveTextContent('could not be used', { exact: false });
  });

  it('rejects an oversized photo before uploading', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockResolvedValue({ canceled: false, assets: [{ ...asset, fileSize: 50 * 1024 * 1024 }] });
    const { navigation } = await renderHome();

    await fireEvent.press(screen.getByTestId('take-photo'));

    expect(await screen.findByTestId('selection-issue')).toHaveTextContent('larger than the 10 MB limit', { exact: false });
    expect(navigation.navigate).not.toHaveBeenCalled();
  });

  it('lets the message be dismissed', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(cameraPermission(false, true));
    await renderHome();

    await fireEvent.press(screen.getByTestId('take-photo'));
    await screen.findByTestId('selection-issue');
    await fireEvent.press(screen.getByText('Dismiss'));

    expect(screen.queryByTestId('selection-issue')).toBeNull();
  });
});
