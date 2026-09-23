/**
 * Naming the photograph a piece of evidence came from.
 *
 * The property under test is restraint: a label is produced only where the
 * backend actually attributed the evidence. Every other case is null, and the
 * interface then says nothing - because "Evidence · Image 1" against a
 * declaration the backend never placed on any panel is the browser inventing a
 * claim about a package.
 */

import { describe, expect, it } from 'vitest';

import { findingImageId, imageLabel, imagePositions } from './images.js';
import { mapInspectionImages } from '../services/extractionService.js';
import {
  IMAGE_ID,
  IMAGE_ID_2,
  IMAGE_ID_3,
  imageSetBody,
} from '../test/fixtures.js';

const threePanels = mapInspectionImages(imageSetBody());
const positions = imagePositions(threePanels);

describe('imagePositions', () => {
  it('maps each stored image id to the position the backend gave it', () => {
    expect(positions.get(IMAGE_ID)).toBe(1);
    expect(positions.get(IMAGE_ID_2)).toBe(2);
    expect(positions.get(IMAGE_ID_3)).toBe(3);
  });

  it('uses the backend position, not the array index', () => {
    // A set whose entries arrive out of order must still name each photograph
    // the way the backend and every other section do.
    const shuffled = imagePositions([
      { position: 3, image: { id: 'c' } },
      { position: 1, image: { id: 'a' } },
    ]);

    expect(shuffled.get('c')).toBe(3);
    expect(shuffled.get('a')).toBe(1);
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
    expect(imageLabel(IMAGE_ID, undefined)).toBeNull();
  });
});

describe('findingImageId', () => {
  const violation = {
    id: 10,
    evidence: [{ excerpt: 'MRP', imageId: IMAGE_ID_2 }],
  };
  const fieldsRead = [
    { fieldKey: 'net_quantity', imageId: IMAGE_ID },
    { fieldKey: 'retail_sale_price', imageId: IMAGE_ID_2 },
  ];

  it('prefers what the backend attributed on the violation', () => {
    const finding = { violationId: 10, fieldKey: 'retail_sale_price' };

    expect(findingImageId(finding, [violation], fieldsRead)).toBe(IMAGE_ID_2);
  });

  it('falls back to the reading when the finding became no violation', () => {
    // A pass has no evidence row, but its excerpt and box were snapshotted
    // from a reading that does name its photograph.
    const finding = { violationId: null, fieldKey: 'net_quantity' };

    expect(findingImageId(finding, [violation], fieldsRead)).toBe(IMAGE_ID);
  });

  it('refuses to choose when two readings share the field key', () => {
    // A declaration printed on two photographed panels. The engine picked one
    // by a rule this layer does not reimplement, so nothing is named.
    const ambiguous = [
      { fieldKey: 'net_quantity', imageId: IMAGE_ID },
      { fieldKey: 'net_quantity', imageId: IMAGE_ID_2 },
    ];
    const finding = { violationId: null, fieldKey: 'net_quantity' };

    expect(findingImageId(finding, [], ambiguous)).toBeNull();
  });

  it('says nothing for a finding about an absence', () => {
    // No field key, so no reading to trace - and the declaration was absent
    // from the whole set rather than from one panel.
    expect(findingImageId({ violationId: null, fieldKey: '' }, [], fieldsRead)).toBeNull();
  });

  it('says nothing when the violation recorded no image', () => {
    const unattributed = { id: 11, evidence: [{ excerpt: 'x', imageId: null }] };
    const finding = { violationId: 11, fieldKey: 'unknown_field' };

    expect(findingImageId(finding, [unattributed], fieldsRead)).toBeNull();
  });

  it('survives missing inputs rather than throwing on a result page', () => {
    expect(findingImageId(null, [], [])).toBeNull();
    expect(findingImageId({ violationId: null, fieldKey: 'x' })).toBeNull();
  });
});
