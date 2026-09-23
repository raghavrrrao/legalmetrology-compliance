/**
 * Camera and library selection, over a mocked expo-image-picker.
 *
 * The module is mocked in tests/setup.ts; what is tested here is the
 * behaviour built on top of it: permissions are asked before the camera
 * opens, a refusal is reported with whether the system will ask again,
 * cancelling is not an error, and the platform's asset is carried through
 * intact.
 */

import * as ImagePicker from 'expo-image-picker';
import { Platform } from 'react-native';

import { captureFromCamera, MAX_SELECTION, pickFromLibrary } from './imagePicker';
import { cameraPermission, libraryPermission } from '../../tests/fixtures';

const picker = ImagePicker as jest.Mocked<typeof ImagePicker>;

const granted = cameraPermission(true);
const denied = cameraPermission(false, true);
const blocked = cameraPermission(false, false);

const asset = {
  uri: 'file:///cache/ImagePicker/abc.jpg',
  fileName: 'abc.jpg',
  mimeType: 'image/jpeg',
  fileSize: 123456,
  width: 3000,
  height: 4000,
};

describe('captureFromCamera', () => {
  it('asks for camera permission before opening the camera', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockResolvedValue({ canceled: false, assets: [asset] });

    const result = await captureFromCamera();

    expect(picker.requestCameraPermissionsAsync).toHaveBeenCalledTimes(1);
    expect(picker.launchCameraAsync).toHaveBeenCalledTimes(1);
    expect(result).toEqual({
      kind: 'selected',
      // A list even for the camera, which returns exactly one: one result
      // vocabulary, so no caller branches on which source it asked for.
      assets: [
        { uri: asset.uri, fileName: 'abc.jpg', mimeType: 'image/jpeg', fileSize: 123456, width: 3000, height: 4000 },
      ],
    });
  });

  it('opens the camera for still images only, without EXIF or base64', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockResolvedValue({ canceled: true, assets: null });

    await captureFromCamera();

    expect(picker.launchCameraAsync).toHaveBeenCalledWith(
      expect.objectContaining({ mediaTypes: ['images'], exif: false, base64: false, allowsEditing: false }),
    );
  });

  it('reports a refusal the system may ask about again', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(denied);

    await expect(captureFromCamera()).resolves.toEqual({ kind: 'permission_denied', canAskAgain: true });
    expect(picker.launchCameraAsync).not.toHaveBeenCalled();
  });

  it('reports a refusal the system will not ask about again', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(blocked);

    await expect(captureFromCamera()).resolves.toEqual({ kind: 'permission_denied', canAskAgain: false });
  });

  it('treats dismissing the camera as a cancellation, not an error', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockResolvedValue({ canceled: true, assets: null });

    await expect(captureFromCamera()).resolves.toEqual({ kind: 'cancelled' });
  });

  it('reports a device with no camera app as unavailable', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockRejectedValue(
      Object.assign(new Error('No activity found to handle intent'), { code: 'ERR_MISSING_ACTIVITY' }),
    );

    await expect(captureFromCamera()).resolves.toEqual({ kind: 'unavailable' });
  });

  it('reports any other failure as an error without throwing', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockRejectedValue(new Error('boom'));

    await expect(captureFromCamera()).resolves.toEqual({ kind: 'error' });
  });

  it('reports an empty non-cancelled result as an error', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockResolvedValue({ canceled: false, assets: [] });

    await expect(captureFromCamera()).resolves.toEqual({ kind: 'error' });
  });

  it('carries missing asset metadata through as null', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValue(granted);
    picker.launchCameraAsync.mockResolvedValue({ canceled: false, assets: [{ uri: 'file:///x.jpg', width: 0, height: 0 }] });

    await expect(captureFromCamera()).resolves.toEqual({
      kind: 'selected',
      assets: [{ uri: 'file:///x.jpg', fileName: null, mimeType: null, fileSize: null, width: null, height: null }],
    });
  });
});

describe('pickFromLibrary', () => {
  const originalOS = Platform.OS;

  afterEach(() => {
    Object.defineProperty(Platform, 'OS', { value: originalOS, configurable: true });
  });

  it('asks for the storage permission on Android before opening the picker', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue(libraryPermission(true));
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: [asset] });

    const result = await pickFromLibrary();

    expect(picker.requestMediaLibraryPermissionsAsync).toHaveBeenCalledTimes(1);
    expect(result.kind).toBe('selected');
  });

  it('reports a refused storage permission on Android', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue(libraryPermission(false, false));

    await expect(pickFromLibrary()).resolves.toEqual({ kind: 'permission_denied', canAskAgain: false });
    expect(picker.launchImageLibraryAsync).not.toHaveBeenCalled();
  });

  it('does not ask for library permission on iOS, where the system picker needs none', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: [asset] });

    const result = await pickFromLibrary();

    expect(picker.requestMediaLibraryPermissionsAsync).not.toHaveBeenCalled();
    expect(result.kind).toBe('selected');
  });

  it('opens the picker for still images, with multiple selection up to the limit', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: true, assets: null });

    await expect(pickFromLibrary()).resolves.toEqual({ kind: 'cancelled' });
    expect(picker.launchImageLibraryAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        mediaTypes: ['images'],
        allowsMultipleSelection: true,
        selectionLimit: MAX_SELECTION,
        exif: false,
      }),
    );
  });

  it('returns every photograph the user chose', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    picker.launchImageLibraryAsync.mockResolvedValue({
      canceled: false,
      assets: [asset, { ...asset, uri: 'file:///back.jpg', fileName: 'back.jpg' }],
    });

    const result = await pickFromLibrary();

    expect(result.kind).toBe('selected');
    expect(result.kind === 'selected' && result.assets.map((one) => one.uri)).toEqual([
      asset.uri,
      'file:///back.jpg',
    ]);
  });

  it('narrows the picker to the room the inspection has left', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: true, assets: null });

    await pickFromLibrary(2);

    // Stopping the user inside the picker is far better than accepting six and
    // refusing three afterwards.
    expect(picker.launchImageLibraryAsync).toHaveBeenCalledWith(
      expect.objectContaining({ selectionLimit: 2, allowsMultipleSelection: true }),
    );
  });

  it('never opens a multiple selection when there is room for one', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: true, assets: null });

    await pickFromLibrary(1);

    expect(picker.launchImageLibraryAsync).toHaveBeenCalledWith(
      expect.objectContaining({ selectionLimit: 1, allowsMultipleSelection: false }),
    );
  });

  it('clamps a limit above the maximum rather than passing it through', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: true, assets: null });

    await pickFromLibrary(99);

    expect(picker.launchImageLibraryAsync).toHaveBeenCalledWith(
      expect.objectContaining({ selectionLimit: MAX_SELECTION }),
    );
  });

  it('drops an asset with no uri rather than returning an unusable selection', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    picker.launchImageLibraryAsync.mockResolvedValue({
      canceled: false,
      // A uri-less asset is off-contract for `ImagePickerAsset`, which is the
      // point: some Android content providers return one, and the cast is how
      // a test reproduces what the platform actually does.
      assets: [asset, { width: 10, height: 10 } as unknown as ImagePicker.ImagePickerAsset],
    });

    const result = await pickFromLibrary();

    expect(result.kind === 'selected' && result.assets).toHaveLength(1);
  });

  it('reports a picker failure as an error', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    picker.launchImageLibraryAsync.mockRejectedValue(new Error('boom'));

    await expect(pickFromLibrary()).resolves.toEqual({ kind: 'error' });
  });
});
