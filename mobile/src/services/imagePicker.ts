/**
 * Camera capture and photo-library selection, with permissions handled.
 *
 * Wraps `expo-image-picker` so every screen sees one result vocabulary rather
 * than the library's exceptions and permission objects. The system camera and
 * the system photo picker are used deliberately: they are what the user
 * already knows, they handle rotation, focus and HDR themselves, and they add
 * no custom viewfinder for this branch to maintain. A live camera preview
 * (`expo-camera`) is a separate decision if a future step needs framing
 * guides or a shutter of its own.
 *
 * Permission semantics, per platform:
 *
 * - **Camera** needs a runtime permission on both platforms. It is requested
 *   here, before the camera is launched, so a refusal can be reported as a
 *   refusal - and, when the system will no longer ask (`canAskAgain` false),
 *   the user can be sent to Settings rather than shown a prompt that never
 *   appears.
 * - **Photo library** is read through the system picker, which needs no
 *   permission on iOS 14+ (PHPicker) or Android 13+ (Photo Picker). On older
 *   Android the storage permission is required and is requested first;
 *   `expo-image-picker` reports it as already granted on 13+. On iOS nothing
 *   is requested, so the app never asks for access to the whole library it
 *   has no need to read.
 *
 * Nothing here validates the image - see `imageValidation.ts` - and nothing
 * here uploads.
 */

import * as ImagePicker from 'expo-image-picker';
import { Platform } from 'react-native';

import type { PickedAsset } from './imageValidation';

export type PickResult =
  /** The user chose a photograph. Not yet validated. */
  | { kind: 'selected'; asset: PickedAsset }
  /** The user dismissed the camera or picker. Not an error. */
  | { kind: 'cancelled' }
  /**
   * The permission was refused. `canAskAgain` false means the system will
   * not show the prompt again and the user must change it in Settings.
   */
  | { kind: 'permission_denied'; canAskAgain: boolean }
  /** No camera, or no app able to take a photo, on this device. */
  | { kind: 'unavailable' }
  /** The picker failed for a reason that is not the user's. */
  | { kind: 'error' };

/**
 * JPEG quality for the camera. Slightly below lossless: a modern phone camera
 * produces a 5-12 MB JPEG at quality 1.0, which is over the backend's limit,
 * and label text survives 0.85 without visible loss. The library path leaves
 * the user's existing photo alone.
 */
const CAMERA_JPEG_QUALITY = 0.85;

function toPickedAsset(asset: ImagePicker.ImagePickerAsset): PickedAsset {
  return {
    uri: asset.uri,
    fileName: asset.fileName ?? null,
    mimeType: asset.mimeType ?? null,
    fileSize: typeof asset.fileSize === 'number' ? asset.fileSize : null,
    width: asset.width || null,
    height: asset.height || null,
  };
}

function fromPickerResult(result: ImagePicker.ImagePickerResult): PickResult {
  if (result.canceled) {
    return { kind: 'cancelled' };
  }
  const asset = result.assets?.[0];
  if (!asset || typeof asset.uri !== 'string' || !asset.uri) {
    // A non-cancelled result with nothing in it: treat as the picker failing
    // rather than as a selection the app cannot use.
    return { kind: 'error' };
  }
  return { kind: 'selected', asset: toPickedAsset(asset) };
}

function isCameraUnavailable(cause: unknown): boolean {
  const code = (cause as { code?: string } | null)?.code ?? '';
  const message = String((cause as { message?: string } | null)?.message ?? '');
  // expo-image-picker: MissingActivityToHandleIntent on Android; on an iOS
  // simulator the camera source is reported unavailable.
  return (
    /MISSING_ACTIVITY|CAMERA_UNAVAILABLE|ERR_MISSING_ACTIVITY/i.test(code)
    || /no activity|not available|camera.*unavailable|unavailable.*camera/i.test(message)
  );
}

/** Take a photograph with the system camera. */
export async function captureFromCamera(): Promise<PickResult> {
  let permission: ImagePicker.PermissionResponse;
  try {
    permission = await ImagePicker.requestCameraPermissionsAsync();
  } catch {
    return { kind: 'error' };
  }
  if (!permission.granted) {
    return { kind: 'permission_denied', canAskAgain: permission.canAskAgain };
  }

  try {
    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ['images'],
      quality: CAMERA_JPEG_QUALITY,
      // No cropping step: the whole label is wanted, and a crop UI between
      // the shutter and the preview is one more place to lose the edge of it.
      allowsEditing: false,
      // Never requested. The photograph is uploaded; its EXIF (which can
      // include a location) has no use here and is not wanted.
      exif: false,
      base64: false,
    });
    return fromPickerResult(result);
  } catch (cause) {
    if (isCameraUnavailable(cause)) {
      return { kind: 'unavailable' };
    }
    return { kind: 'error' };
  }
}

/** Choose an existing photograph with the system photo picker. */
export async function pickFromLibrary(): Promise<PickResult> {
  if (Platform.OS === 'android') {
    // A no-op on Android 13+ (the module returns granted without prompting);
    // the storage permission on older versions.
    let permission: ImagePicker.PermissionResponse;
    try {
      permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    } catch {
      return { kind: 'error' };
    }
    if (!permission.granted) {
      return { kind: 'permission_denied', canAskAgain: permission.canAskAgain };
    }
  }

  try {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsMultipleSelection: false,
      allowsEditing: false,
      exif: false,
      base64: false,
    });
    return fromPickerResult(result);
  } catch {
    return { kind: 'error' };
  }
}
