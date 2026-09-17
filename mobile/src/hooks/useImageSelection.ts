/**
 * Pick a photograph - from the camera or the library - and pre-check it.
 *
 * Joins `services/imagePicker.ts` (which talks to the platform) and
 * `services/imageValidation.ts` (which checks what came back) into the one
 * outcome a screen needs: a `SelectedImage` to go on with, or an `issue` to
 * show. Cancelling is neither: it resolves to null and shows nothing, because
 * dismissing the camera is not an error.
 */

import { useCallback, useRef, useState } from 'react';

import { captureFromCamera, pickFromLibrary } from '../services/imagePicker';
import {
  validatePickedImage,
  type ImageRejectionReason,
  type SelectedImage,
} from '../services/imageValidation';

export type ImageSource = 'camera' | 'library';

export type SelectionIssue =
  | { kind: 'permission_denied'; source: ImageSource; canAskAgain: boolean }
  | { kind: 'unavailable'; source: ImageSource }
  | { kind: 'rejected'; source: ImageSource; reason: ImageRejectionReason; message: string }
  | { kind: 'error'; source: ImageSource };

export interface ImageSelection {
  issue: SelectionIssue | null;
  isPicking: boolean;
  /** Resolves to the image, or null when the user cancelled or something went wrong (see `issue`). */
  select: (source: ImageSource) => Promise<SelectedImage | null>;
  clearIssue: () => void;
}

export function useImageSelection(): ImageSelection {
  const [issue, setIssue] = useState<SelectionIssue | null>(null);
  const [isPicking, setIsPicking] = useState(false);
  // A second tap while the system picker is opening would open it twice.
  const pickingRef = useRef(false);

  const clearIssue = useCallback(() => setIssue(null), []);

  const select = useCallback(async (source: ImageSource): Promise<SelectedImage | null> => {
    if (pickingRef.current) {
      return null;
    }
    pickingRef.current = true;
    setIsPicking(true);
    setIssue(null);

    try {
      const picked = source === 'camera' ? await captureFromCamera() : await pickFromLibrary();

      switch (picked.kind) {
        case 'cancelled':
          return null;
        case 'permission_denied':
          setIssue({ kind: 'permission_denied', source, canAskAgain: picked.canAskAgain });
          return null;
        case 'unavailable':
          setIssue({ kind: 'unavailable', source });
          return null;
        case 'error':
          setIssue({ kind: 'error', source });
          return null;
        case 'selected': {
          const validation = validatePickedImage(picked.asset);
          if (!validation.ok) {
            setIssue({ kind: 'rejected', source, reason: validation.reason, message: validation.message });
            return null;
          }
          return validation.image;
        }
        default:
          return null;
      }
    } finally {
      pickingRef.current = false;
      setIsPicking(false);
    }
  }, []);

  return { issue, isPicking, select, clearIssue };
}
