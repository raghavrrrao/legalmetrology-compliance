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
 * Selecting more than one
 * -----------------------
 * An inspection may carry several photographs of the same package, so the
 * photo picker is opened with multiple selection enabled and a limit. Both
 * system pickers support it natively - iOS PHPicker and the Android Photo
 * Picker - so this needs no custom grid and no extra permission.
 *
 * The **camera** stays one photograph per launch, and that is the platform's
 * shape rather than a limitation of this file: neither system camera returns a
 * batch. Taking several is taking one, returning to the app, and tapping add
 * again - which is also the only arrangement in which the user gets to see
 * each photograph before deciding to keep it.
 *
 * `PickResult` carries a list in every case, including the camera's one. A
 * separate single-asset shape would mean two result vocabularies for the same
 * question, and every caller branching on which it got.
 *
 * Nothing here validates the image - see `imageValidation.ts` - and nothing
 * here uploads.
 */

import * as ImagePicker from 'expo-image-picker';
import { Platform } from 'react-native';

import type { PickedAsset } from './imageValidation';

export type PickResult =
  /**
   * The user chose at least one photograph. Not yet validated.
   *
   * `assets` is always non-empty - a picker that returns nothing without
   * having been cancelled is reported as an error, not as an empty selection.
   * The camera returns exactly one.
   */
  | { kind: 'selected'; assets: PickedAsset[] }
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

/**
 * How many photographs the gallery picker will return in one go.
 *
 * Mirrors the backend's `MAX_IMAGES_PER_INSPECTION`, so the system picker stops
 * the user at the same number the server would - a refusal inside the picker,
 * where the user is choosing, is far better than an error after the upload.
 * The caller reduces it further when some photographs have already been added.
 */
export const MAX_SELECTION = 6;

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
  const assets = (result.assets ?? [])
    .filter((asset) => typeof asset?.uri === 'string' && asset.uri)
    .map(toPickedAsset);
  if (assets.length === 0) {
    // A non-cancelled result with nothing usable in it: treat as the picker
    // failing rather than as a selection the app cannot use. Reporting it as
    // an empty selection would silently drop the user's choice.
    return { kind: 'error' };
  }
  return { kind: 'selected', assets };
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

/**
 * Choose existing photographs with the system photo picker.
 *
 * @param limit How many may be chosen. Clamped to at least one, and to
 *   `MAX_SELECTION` - the caller passes the room it has left so the picker
 *   itself stops the user rather than the app rejecting the extras afterwards.
 */
export async function pickFromLibrary(limit: number = MAX_SELECTION): Promise<PickResult> {
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

  const selectionLimit = Math.max(1, Math.min(limit, MAX_SELECTION));

  try {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      // A package declares different things on different panels, so several
      // photographs of one package is the ordinary case rather than an
      // advanced one.
      allowsMultipleSelection: selectionLimit > 1,
      selectionLimit,
      allowsEditing: false,
      exif: false,
      base64: false,
    });
    return fromPickerResult(result);
  } catch {
    return { kind: 'error' };
  }
}
