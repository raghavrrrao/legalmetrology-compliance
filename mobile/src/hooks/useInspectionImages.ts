/**
 * The photographs of the inspection being composed, before it is submitted.
 *
 * One package, several panels: the user takes the front, adds the back, adds a
 * close-up of a small declaration, removes the one that came out blurred, and
 * submits the set. This hook owns that list and nothing else - it does not
 * pick, it does not validate and it does not upload.
 *
 * It lives beside `useLabelAnalysis` in the same provider rather than in a
 * screen's state, for the reason the analysis does: the list has to survive
 * navigating to the progress screen and back after a failure. Losing a user's
 * four photographs because a request timed out would be the worst thing this
 * feature could do to them, and route params or screen state would do exactly
 * that.
 *
 * Two rules it enforces, both about not submitting something unintended:
 *
 * 1. **A photograph cannot be added twice.** The gallery picker will happily
 *    return the same file again on a second visit, and a duplicate would have
 *    its declarations read and counted twice. De-duplicated on `uri`, which is
 *    what identifies a file on the device.
 * 2. **The set is bounded**, at the number the backend accepts. Reaching it
 *    disables adding rather than failing the upload.
 */

import { useCallback, useMemo, useState } from 'react';

import { MAX_INSPECTION_IMAGES } from '../config/env';
import type { SelectedImage } from '../services/imageValidation';

/** Why an add was refused, when it was. */
export type AddRejection =
  | { kind: 'duplicate'; count: number }
  | { kind: 'full'; added: number; refused: number };

export interface AddOutcome {
  /** How many photographs actually joined the set. */
  added: number;
  /** Set when some were refused; null when everything was taken. */
  rejection: AddRejection | null;
}

export interface InspectionImages {
  /** The set, in the order it will be submitted. Position 1 is first. */
  images: SelectedImage[];
  count: number;
  /** False once the set is at the backend's limit. */
  canAddMore: boolean;
  /** How many more may be added. Zero when full. */
  remaining: number;
  /** The most recent refusal, or null. Cleared by `clearRejection`. */
  rejection: AddRejection | null;
  add: (images: SelectedImage[]) => AddOutcome;
  /** Remove the photograph at `index`. Out-of-range indices are ignored. */
  remove: (index: number) => void;
  replaceAll: (images: SelectedImage[]) => void;
  clear: () => void;
  clearRejection: () => void;
}

export function useInspectionImages(): InspectionImages {
  const [images, setImages] = useState<SelectedImage[]>([]);
  const [rejection, setRejection] = useState<AddRejection | null>(null);

  const add = useCallback((incoming: SelectedImage[]): AddOutcome => {
    let outcome: AddOutcome = { added: 0, rejection: null };

    setImages((current) => {
      const seen = new Set(current.map((image) => image.uri));
      const fresh: SelectedImage[] = [];
      let duplicates = 0;

      for (const image of incoming) {
        if (seen.has(image.uri)) {
          duplicates += 1;
          continue;
        }
        seen.add(image.uri);
        fresh.push(image);
      }

      const room = Math.max(0, MAX_INSPECTION_IMAGES - current.length);
      const taken = fresh.slice(0, room);
      const overflow = fresh.length - taken.length;

      // The refusal the user most needs to hear about wins. Being over the
      // limit is actionable - remove one, add another; a duplicate is merely
      // a no-op they should not be left puzzling over.
      const refusal: AddRejection | null = overflow > 0
        ? { kind: 'full', added: taken.length, refused: overflow }
        : duplicates > 0
          ? { kind: 'duplicate', count: duplicates }
          : null;

      outcome = { added: taken.length, rejection: refusal };
      setRejection(refusal);

      return taken.length > 0 ? [...current, ...taken] : current;
    });

    return outcome;
  }, []);

  const remove = useCallback((index: number) => {
    setRejection(null);
    setImages((current) =>
      index < 0 || index >= current.length
        ? current
        : current.filter((_image, position) => position !== index),
    );
  }, []);

  const replaceAll = useCallback((next: SelectedImage[]) => {
    setRejection(null);
    setImages(next.slice(0, MAX_INSPECTION_IMAGES));
  }, []);

  const clear = useCallback(() => {
    setRejection(null);
    setImages([]);
  }, []);

  const clearRejection = useCallback(() => setRejection(null), []);

  return useMemo(
    () => ({
      images,
      count: images.length,
      canAddMore: images.length < MAX_INSPECTION_IMAGES,
      remaining: Math.max(0, MAX_INSPECTION_IMAGES - images.length),
      rejection,
      add,
      remove,
      replaceAll,
      clear,
      clearRejection,
    }),
    [images, rejection, add, remove, replaceAll, clear, clearRejection],
  );
}
