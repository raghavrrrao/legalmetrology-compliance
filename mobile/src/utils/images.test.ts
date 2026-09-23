/**
 * Naming the photograph a piece of evidence came from.
 *
 * The property under test is restraint: a label is produced only where the
 * backend actually attributed the evidence to an image. Every other case is
 * null, and the interface says nothing - because "Evidence · Image 1" against
 * a declaration the backend never placed on any panel is the app inventing a
 * claim about a package.
 */

import { imageLabel, imagePositions } from './images';
import { IMAGE_ID, IMAGE_ID_2, IMAGE_ID_3, imageSetBody } from '../../tests/fixtures';
import { mapInspectionImages } from '../api/extraction';

const threePanels = mapInspectionImages(imageSetBody());
const positions = imagePositions(threePanels);

describe('imagePositions', () => {
  it('maps each stored image id to the position the backend gave it', () => {
    expect(positions.get(IMAGE_ID)).toBe(1);
    expect(positions.get(IMAGE_ID_2)).toBe(2);
    expect(positions.get(IMAGE_ID_3)).toBe(3);
  });

  it('uses the backend position, not the array index', () => {
    // A set whose entries arrive out of order, or with a gap, must still name
    // each photograph the way the result screen and the backend do.
    const shuffled = mapInspectionImages([
      { position: 3, status: 'completed', image: { id: 'c', original_filename: 'c.jpg', image_format: 'jpeg', width: 1, height: 1, size_bytes: 1, view_type: 'unspecified', status: 'processed' } },
      { position: 1, status: 'completed', image: { id: 'a', original_filename: 'a.jpg', image_format: 'jpeg', width: 1, height: 1, size_bytes: 1, view_type: 'unspecified', status: 'processed' } },
    ]);

    const map = imagePositions(shuffled);
    expect(map.get('c')).toBe(3);
    expect(map.get('a')).toBe(1);
  });
});

describe('imageLabel', () => {
  it('names the photograph an id belongs to', () => {
    expect(imageLabel(IMAGE_ID_2, positions)).toBe('Image 2');
  });

  it('says nothing when the backend recorded no source', () => {
    // An older server, or a reading whose image row has been deleted. Not a
    // claim that no photograph was involved.
    expect(imageLabel(null, positions)).toBeNull();
    expect(imageLabel(undefined, positions)).toBeNull();
  });

  it('says nothing for an id that is not in this result', () => {
    expect(imageLabel('not-in-this-inspection', positions)).toBeNull();
  });

  it('says nothing when the inspection has only one photograph', () => {
    const single = imagePositions(mapInspectionImages([imageSetBody()[0]]));

    // "Image 1" beside every finding of a single-photo inspection is noise,
    // not information.
    expect(imageLabel(IMAGE_ID, single)).toBeNull();
  });

  it('says nothing when there are no photographs at all', () => {
    expect(imageLabel(IMAGE_ID, imagePositions([]))).toBeNull();
  });
});
