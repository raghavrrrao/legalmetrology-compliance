/**
 * Pick photographs - from the camera or the library - and pre-check them.
 *
 * Joins `services/imagePicker.ts` (which talks to the platform) and
 * `services/imageValidation.ts` (which checks what came back) into the one
 * outcome a screen needs: the `SelectedImage`s to go on with, or an `issue` to
 * show. Cancelling is neither: it resolves to an empty list and shows nothing,
 * because dismissing the camera is not an error.
 *
 * An inspection may carry several photographs of one package, so `select`
 * always resolves to a **list**. The camera returns one, the gallery returns
 * as many as the user chose up to `limit`. One result vocabulary rather than
 * two, so no caller has to branch on which source it asked for.
 *
 * **A rejected photograph does not discard the acceptable ones.** When the user
 * picks four and one is a HEIC, the three that passed are returned and the
 * issue names the one that did not. Throwing the whole selection away would
 * make the user repeat a choice that was mostly fine, and it is their photo
 * library - they cannot fix the format of a file the picker offered them.
 */

import { useCallback, useRef, useState } from 'react';

import { captureFromCamera, MAX_SELECTION, pickFromLibrary } from '../services/imagePicker';
import {
  validatePickedImage,
  type ImageRejectionReason,
  type SelectedImage,
} from '../services/imageValidation';

export type ImageSource = 'camera' | 'library';

export type SelectionIssue =
  | { kind: 'permission_denied'; source: ImageSource; canAskAgain: boolean }
  | { kind: 'unavailable'; source: ImageSource }
  | {
      kind: 'rejected';
      source: ImageSource;
      reason: ImageRejectionReason;
      message: string;
      /**
       * How many of the chosen photographs were refused, and how many were
       * kept. Both are needed to write an honest message: "1 of 4 photos could
       * not be used" says something different from "this photo cannot be used",
       * and the second would be a lie about the other three.
       */
      rejectedCount: number;
      acceptedCount: number;
    }
  | { kind: 'error'; source: ImageSource };

export interface SelectOptions {
  /**
   * How many photographs may be returned. The screen passes the room left in
   * the inspection, so the system picker stops the user at the right number
   * rather than the app discarding their extras afterwards.
   */
  limit?: number;
}

export interface ImageSelection {
  issue: SelectionIssue | null;
  isPicking: boolean;
  /**
   * Resolves to the photographs that passed the pre-checks. Empty when the
   * user cancelled, when a permission was refused, or when every photograph
   * they chose was rejected - `issue` says which.
   */
  select: (source: ImageSource, options?: SelectOptions) => Promise<SelectedImage[]>;
  clearIssue: () => void;
}

export function useImageSelection(): ImageSelection {
  const [issue, setIssue] = useState<SelectionIssue | null>(null);
  const [isPicking, setIsPicking] = useState(false);
  // A second tap while the system picker is opening would open it twice.
  const pickingRef = useRef(false);

  const clearIssue = useCallback(() => setIssue(null), []);

  const select = useCallback(
    async (source: ImageSource, options: SelectOptions = {}): Promise<SelectedImage[]> => {
      if (pickingRef.current) {
        return [];
      }
      pickingRef.current = true;
      setIsPicking(true);
      setIssue(null);

      const limit = Math.max(1, Math.min(options.limit ?? MAX_SELECTION, MAX_SELECTION));

      try {
        const picked =
          source === 'camera' ? await captureFromCamera() : await pickFromLibrary(limit);

        switch (picked.kind) {
          case 'cancelled':
            return [];
          case 'permission_denied':
            setIssue({ kind: 'permission_denied', source, canAskAgain: picked.canAskAgain });
            return [];
          case 'unavailable':
            setIssue({ kind: 'unavailable', source });
            return [];
          case 'error':
            setIssue({ kind: 'error', source });
            return [];
          case 'selected': {
            const accepted: SelectedImage[] = [];
            let firstRejection: { reason: ImageRejectionReason; message: string } | null = null;
            let rejectedCount = 0;

            // A defence in depth against a picker that ignored `selectionLimit`
            // - some Android OEM pickers do. The user is told, rather than
            // having the extras silently vanish.
            for (const asset of picked.assets.slice(0, limit)) {
              const validation = validatePickedImage(asset);
              if (validation.ok) {
                accepted.push(validation.image);
              } else {
                rejectedCount += 1;
                // The first rejection's words are shown. Listing every reason
                // for a mixed selection would be a wall of text about files
                // the user did not choose deliberately.
                firstRejection ??= { reason: validation.reason, message: validation.message };
              }
            }

            if (firstRejection) {
              setIssue({
                kind: 'rejected',
                source,
                reason: firstRejection.reason,
                message: firstRejection.message,
                rejectedCount,
                acceptedCount: accepted.length,
              });
            }
            return accepted;
          }
          default:
            return [];
        }
      } finally {
        pickingRef.current = false;
        setIsPicking(false);
      }
    },
    [],
  );

  return { issue, isPicking, select, clearIssue };
}
