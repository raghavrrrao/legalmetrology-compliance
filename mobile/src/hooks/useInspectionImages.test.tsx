/**
 * The set of photographs being gathered for one inspection.
 *
 * The two rules worth testing are both about not submitting something
 * unintended: a photograph cannot join the set twice, and the set cannot grow
 * past what the backend accepts. Everything else here is list handling, and it
 * is tested because a bug in it loses a user's photographs.
 */

import { act, renderHook } from '@testing-library/react-native';

import { useInspectionImages } from './useInspectionImages';
import { selectedImage, selectedImages } from '../../tests/fixtures';
import { MAX_INSPECTION_IMAGES } from '../config/env';

describe('useInspectionImages', () => {
  it('starts empty, and says so in every form a screen reads', async () => {
    const { result } = await renderHook(() => useInspectionImages());

    expect(result.current.images).toEqual([]);
    expect(result.current.count).toBe(0);
    expect(result.current.canAddMore).toBe(true);
    expect(result.current.remaining).toBe(MAX_INSPECTION_IMAGES);
    expect(result.current.rejection).toBeNull();
  });

  it('keeps added photos in the order they arrived', async () => {
    const { result } = await renderHook(() => useInspectionImages());
    const [first, second, third] = selectedImages(3);

    await act(async () => {
      result.current.add([first]);
    });
    await act(async () => {
      result.current.add([second, third]);
    });

    // The order becomes the position the backend records and the number the
    // user is shown, so it is not incidental.
    expect(result.current.images.map((image) => image.name)).toEqual([
      'panel-1.jpg',
      'panel-2.jpg',
      'panel-3.jpg',
    ]);
    expect(result.current.count).toBe(3);
  });

  // --- duplicates ------------------------------------------------------------

  it('refuses a photo that is already in the set', async () => {
    const { result } = await renderHook(() => useInspectionImages());
    const image = selectedImage();

    await act(async () => {
      result.current.add([image]);
    });
    await act(async () => {
      result.current.add([image]);
    });

    // Adding it twice would have its declarations read and counted twice.
    expect(result.current.count).toBe(1);
    expect(result.current.rejection).toEqual({ kind: 'duplicate', count: 1 });
  });

  it('takes the new photos out of a selection that also repeats an old one', async () => {
    const { result } = await renderHook(() => useInspectionImages());
    const [first, second] = selectedImages(2);

    await act(async () => {
      result.current.add([first]);
    });
    await act(async () => {
      result.current.add([first, second]);
    });

    expect(result.current.images.map((image) => image.name)).toEqual(['panel-1.jpg', 'panel-2.jpg']);
    expect(result.current.rejection).toEqual({ kind: 'duplicate', count: 1 });
  });

  it('de-duplicates within a single selection', async () => {
    const { result } = await renderHook(() => useInspectionImages());
    const image = selectedImage();

    await act(async () => {
      result.current.add([image, image]);
    });

    expect(result.current.count).toBe(1);
  });

  // --- the limit ------------------------------------------------------------

  it('stops at the maximum and says how many were refused', async () => {
    const { result } = await renderHook(() => useInspectionImages());

    await act(async () => {
      result.current.add(selectedImages(MAX_INSPECTION_IMAGES + 2));
    });

    expect(result.current.count).toBe(MAX_INSPECTION_IMAGES);
    expect(result.current.canAddMore).toBe(false);
    expect(result.current.remaining).toBe(0);
    expect(result.current.rejection).toEqual({
      kind: 'full',
      added: MAX_INSPECTION_IMAGES,
      refused: 2,
    });
  });

  it('keeps the photos that fit rather than refusing the whole selection', async () => {
    const { result } = await renderHook(() => useInspectionImages());

    await act(async () => {
      result.current.add(selectedImages(MAX_INSPECTION_IMAGES - 1));
    });
    await act(async () => {
      result.current.add([
        selectedImage({ uri: 'file:///a.jpg', name: 'a.jpg' }),
        selectedImage({ uri: 'file:///b.jpg', name: 'b.jpg' }),
      ]);
    });

    expect(result.current.count).toBe(MAX_INSPECTION_IMAGES);
    expect(result.current.images.at(-1)?.name).toBe('a.jpg');
    expect(result.current.rejection).toEqual({ kind: 'full', added: 1, refused: 1 });
  });

  it('reports being over the limit in preference to a duplicate', async () => {
    const { result } = await renderHook(() => useInspectionImages());
    const existing = selectedImages(MAX_INSPECTION_IMAGES);

    await act(async () => {
      result.current.add(existing);
    });
    await act(async () => {
      result.current.add([existing[0], selectedImage({ uri: 'file:///new.jpg', name: 'new.jpg' })]);
    });

    // Being full is actionable - remove one, add another. A duplicate is a
    // no-op the user should not be left puzzling over.
    expect(result.current.rejection).toEqual({ kind: 'full', added: 0, refused: 1 });
  });

  it('returns what happened to the caller, not only to the screen', async () => {
    const { result } = await renderHook(() => useInspectionImages());
    let outcome: { added: number } | undefined;

    await act(async () => {
      outcome = result.current.add(selectedImages(2));
    });

    expect(outcome).toEqual({ added: 2, rejection: null });
  });

  // --- removing --------------------------------------------------------------

  it('removes the photo at the given position and closes the gap', async () => {
    const { result } = await renderHook(() => useInspectionImages());

    await act(async () => {
      result.current.add(selectedImages(3));
    });
    await act(async () => {
      result.current.remove(1);
    });

    expect(result.current.images.map((image) => image.name)).toEqual(['panel-1.jpg', 'panel-3.jpg']);
    expect(result.current.count).toBe(2);
  });

  it('makes room again after a removal', async () => {
    const { result } = await renderHook(() => useInspectionImages());

    await act(async () => {
      result.current.add(selectedImages(MAX_INSPECTION_IMAGES));
    });
    await act(async () => {
      result.current.remove(0);
    });

    expect(result.current.canAddMore).toBe(true);
    expect(result.current.remaining).toBe(1);
  });

  it('lets a removed photo be added back', async () => {
    const { result } = await renderHook(() => useInspectionImages());
    const image = selectedImage();

    await act(async () => {
      result.current.add([image]);
    });
    await act(async () => {
      result.current.remove(0);
    });
    await act(async () => {
      result.current.add([image]);
    });

    // De-duplication is about the set as it stands, not a history of it.
    expect(result.current.count).toBe(1);
    expect(result.current.rejection).toBeNull();
  });

  it('ignores a position that is not in the set', async () => {
    const { result } = await renderHook(() => useInspectionImages());

    await act(async () => {
      result.current.add(selectedImages(2));
    });
    await act(async () => {
      result.current.remove(7);
      result.current.remove(-1);
    });

    expect(result.current.count).toBe(2);
  });

  it('clears a refusal when a photo is removed', async () => {
    const { result } = await renderHook(() => useInspectionImages());

    await act(async () => {
      result.current.add(selectedImages(MAX_INSPECTION_IMAGES + 1));
    });
    expect(result.current.rejection).not.toBeNull();

    await act(async () => {
      result.current.remove(0);
    });

    // The message said "remove one to make room", and they did.
    expect(result.current.rejection).toBeNull();
  });

  // --- clearing --------------------------------------------------------------

  it('empties the set', async () => {
    const { result } = await renderHook(() => useInspectionImages());

    await act(async () => {
      result.current.add(selectedImages(3));
    });
    await act(async () => {
      result.current.clear();
    });

    expect(result.current.images).toEqual([]);
    expect(result.current.rejection).toBeNull();
  });

  it('replaces the set wholesale, bounded by the maximum', async () => {
    const { result } = await renderHook(() => useInspectionImages());

    await act(async () => {
      result.current.add(selectedImages(2));
    });
    await act(async () => {
      result.current.replaceAll(selectedImages(MAX_INSPECTION_IMAGES + 3));
    });

    expect(result.current.count).toBe(MAX_INSPECTION_IMAGES);
  });

  it('dismisses a refusal without touching the set', async () => {
    const { result } = await renderHook(() => useInspectionImages());

    await act(async () => {
      result.current.add(selectedImages(MAX_INSPECTION_IMAGES + 1));
    });
    await act(async () => {
      result.current.clearRejection();
    });

    expect(result.current.rejection).toBeNull();
    expect(result.current.count).toBe(MAX_INSPECTION_IMAGES);
  });
});
