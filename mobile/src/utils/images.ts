/**
 * Naming the photograph a piece of evidence came from.
 *
 * One function, used by every surface that mentions an image, so the label on
 * the scan screen ("Image 2"), the one on a finding ("Evidence · Image 2") and
 * the one in the extracted-declarations list all mean the same photograph. A
 * number that moved between screens would be worse than no number.
 *
 * The number is the backend's `position`, never an array index. They agree
 * today, and the moment they stop agreeing - a backend that omits a
 * photograph, a client that filters one - the index would quietly start
 * pointing at the wrong panel.
 */

import type { InspectionImage } from '../types/api';

/** Position lookup by stored image id, built once per render of a result. */
export type ImagePositions = Map<string, number>;

export function imagePositions(images: InspectionImage[]): ImagePositions {
  return new Map(images.map((entry) => [entry.image.id, entry.position]));
}

/**
 * "Image 2" for a stored image id, or null when it cannot be named.
 *
 * Null in three real cases, and all three mean the same thing to the
 * interface - **say nothing about which photograph**:
 *
 * - the backend did not record a source for this reading (an older server, or
 *   an image row since deleted);
 * - the id names no photograph in this result;
 * - there is only one photograph, where "Image 1" is noise rather than
 *   information.
 *
 * Never a guess. Labelling evidence with a photograph the backend did not
 * attribute it to would be the app inventing a claim about where a declaration
 * appears on a package.
 */
export function imageLabel(
  imageId: string | null | undefined,
  positions: ImagePositions,
): string | null {
  if (!imageId || positions.size < 2) {
    return null;
  }
  const position = positions.get(imageId);
  return position === undefined ? null : `Image ${position}`;
}
