/**
 * The set of photographs being gathered for one inspection.
 *
 * `triageFiles` is pure and gets the bulk of these, because the order of its
 * checks is the order the messages appear in: telling somebody their file was
 * a duplicate when it was actually the seventh is a worse failure than either
 * message alone. The hook's own tests cover the parts that are stateful - the
 * list, and the object URLs behind it.
 */

import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { triageFiles, useSelectedImages } from './useSelectedImages.js';
import { MAX_INSPECTION_IMAGES } from '../config/env.js';

function png(name = 'label.png', { size = 5, lastModified = 1 } = {}) {
  const file = new File(['bytes'], name, { type: 'image/png' });
  // jsdom computes size from the parts; override so a test can make two files
  // differ in exactly one respect.
  Object.defineProperty(file, 'size', { value: size });
  Object.defineProperty(file, 'lastModified', { value: lastModified });
  return file;
}

function entriesFor(files) {
  return files.map((file, index) => ({ id: `e${index}`, file }));
}

describe('triageFiles', () => {
  it('accepts the formats the API reads', () => {
    const files = [
      png('a.png'),
      new File(['x'], 'b.jpg', { type: 'image/jpeg' }),
      new File(['x'], 'c.webp', { type: 'image/webp' }),
    ];

    const { accepted, rejections } = triageFiles([], files);

    expect(accepted).toHaveLength(3);
    expect(rejections).toEqual([]);
  });

  it('refuses a format the API does not read, and names it', () => {
    const { accepted, rejections } = triageFiles([], [
      png('good.png'),
      new File(['x'], 'scan.pdf', { type: 'application/pdf' }),
    ]);

    // The acceptable one is kept: throwing the whole selection away would make
    // the user repeat a choice that was mostly fine.
    expect(accepted.map((file) => file.name)).toEqual(['good.png']);
    expect(rejections).toEqual([{ kind: 'unsupported', files: ['scan.pdf'] }]);
  });

  it('refuses an empty file', () => {
    const { accepted, rejections } = triageFiles([], [png('empty.png', { size: 0 })]);

    expect(accepted).toEqual([]);
    expect(rejections).toEqual([{ kind: 'empty', files: ['empty.png'] }]);
  });

  it('refuses a file already in the set', () => {
    const existing = png('front.png');

    const { accepted, rejections } = triageFiles(entriesFor([existing]), [existing]);

    expect(accepted).toEqual([]);
    expect(rejections).toEqual([{ kind: 'duplicate', files: ['front.png'] }]);
  });

  it('treats name, size and last-modified together as identity', () => {
    const existing = png('front.png', { size: 10, lastModified: 100 });
    // Same name, different bytes: a different photograph the user renamed, or
    // re-exported. Not a duplicate.
    const different = png('front.png', { size: 20, lastModified: 200 });

    const { accepted } = triageFiles(entriesFor([existing]), [different]);

    expect(accepted).toHaveLength(1);
  });

  it('de-duplicates within one selection', () => {
    const file = png('front.png');

    const { accepted, rejections } = triageFiles([], [file, file]);

    expect(accepted).toHaveLength(1);
    expect(rejections).toEqual([{ kind: 'duplicate', files: ['front.png'] }]);
  });

  it('stops at the maximum and names what did not fit', () => {
    const files = Array.from({ length: MAX_INSPECTION_IMAGES + 2 }, (_v, i) =>
      png(`p${i}.png`, { lastModified: i }),
    );

    const { accepted, rejections } = triageFiles([], files);

    expect(accepted).toHaveLength(MAX_INSPECTION_IMAGES);
    expect(rejections).toEqual([
      { kind: 'overflow', files: ['p6.png', 'p7.png'] },
    ]);
  });

  it('counts the room already taken', () => {
    const existing = Array.from({ length: 5 }, (_v, i) =>
      png(`old${i}.png`, { lastModified: i }),
    );

    const { accepted, rejections } = triageFiles(entriesFor(existing), [
      png('a.png', { lastModified: 90 }),
      png('b.png', { lastModified: 91 }),
    ]);

    expect(accepted.map((file) => file.name)).toEqual(['a.png']);
    expect(rejections).toEqual([{ kind: 'overflow', files: ['b.png'] }]);
  });

  it('checks the format before the count, so the message is the useful one', () => {
    const existing = Array.from({ length: MAX_INSPECTION_IMAGES }, (_v, i) =>
      png(`old${i}.png`, { lastModified: i }),
    );

    const { rejections } = triageFiles(entriesFor(existing), [
      new File(['x'], 'scan.pdf', { type: 'application/pdf' }),
    ]);

    // A PDF is not "the seventh photo" - it would not have been accepted as
    // the first, and telling the user to remove one to make room for it would
    // send them down a path that ends in the same refusal.
    expect(rejections).toEqual([{ kind: 'unsupported', files: ['scan.pdf'] }]);
  });

  it('reports several kinds of refusal at once', () => {
    const existing = png('front.png');

    const { rejections } = triageFiles(entriesFor([existing]), [
      new File(['x'], 'scan.pdf', { type: 'application/pdf' }),
      existing,
    ]);

    expect(rejections.map((entry) => entry.kind)).toEqual([
      'unsupported',
      'duplicate',
    ]);
  });
});

describe('useSelectedImages', () => {
  beforeEach(() => {
    let counter = 0;
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => `blob:url-${(counter += 1)}`),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('starts empty, and says so in every form the screen reads', () => {
    const { result } = renderHook(() => useSelectedImages());

    expect(result.current.entries).toEqual([]);
    expect(result.current.count).toBe(0);
    expect(result.current.canAddMore).toBe(true);
    expect(result.current.remaining).toBe(MAX_INSPECTION_IMAGES);
    expect(result.current.rejections).toEqual([]);
  });

  it('keeps added photos in the order they arrived', () => {
    const { result } = renderHook(() => useSelectedImages());

    act(() => {
      result.current.add([png('a.png', { lastModified: 1 })]);
    });
    act(() => {
      result.current.add([
        png('b.png', { lastModified: 2 }),
        png('c.png', { lastModified: 3 }),
      ]);
    });

    // The order becomes the position the backend records and the number the
    // user is shown, so it is not incidental.
    expect(result.current.files.map((file) => file.name)).toEqual([
      'a.png',
      'b.png',
      'c.png',
    ]);
  });

  it('gives every photo a preview URL', () => {
    const { result } = renderHook(() => useSelectedImages());

    act(() => {
      result.current.add([png('a.png', { lastModified: 1 })]);
    });

    expect(result.current.entries[0].previewUrl).toMatch(/^blob:/);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it('revokes the URL of a photo that is removed', () => {
    const { result } = renderHook(() => useSelectedImages());

    act(() => {
      result.current.add([png('a.png', { lastModified: 1 })]);
    });
    const { id, previewUrl } = result.current.entries[0];
    act(() => {
      result.current.remove(id);
    });

    // An object URL that is never revoked keeps the whole image alive in
    // memory for the life of the tab, and six of them is no rounding error.
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(previewUrl);
    expect(result.current.count).toBe(0);
  });

  it('revokes every URL on unmount', () => {
    const { result, unmount } = renderHook(() => useSelectedImages());

    act(() => {
      result.current.add([
        png('a.png', { lastModified: 1 }),
        png('b.png', { lastModified: 2 }),
      ]);
    });
    unmount();

    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it('ignores a cancelled picker without clearing the refusals on screen', () => {
    const { result } = renderHook(() => useSelectedImages());

    act(() => {
      result.current.add([new File(['x'], 'a.pdf', { type: 'application/pdf' })]);
    });
    expect(result.current.rejections).toHaveLength(1);

    act(() => {
      result.current.add([]);
    });

    // Dismissing a message the user has not read yet, because they opened and
    // closed the picker, would be worse than leaving it.
    expect(result.current.rejections).toHaveLength(1);
  });

  it('makes room again after a removal', () => {
    const { result } = renderHook(() => useSelectedImages());

    act(() => {
      result.current.add(
        Array.from({ length: MAX_INSPECTION_IMAGES }, (_v, i) =>
          png(`p${i}.png`, { lastModified: i }),
        ),
      );
    });
    expect(result.current.canAddMore).toBe(false);

    act(() => {
      result.current.remove(result.current.entries[0].id);
    });

    expect(result.current.canAddMore).toBe(true);
    expect(result.current.remaining).toBe(1);
  });

  it('records the panel stated for one photo, and only that one', () => {
    const { result } = renderHook(() => useSelectedImages());

    act(() => {
      result.current.add([
        png('a.png', { lastModified: 1 }),
        png('b.png', { lastModified: 2 }),
      ]);
    });
    act(() => {
      result.current.setViewType(result.current.entries[1].id, 'back');
    });

    // Positional on the API: saying the second is the back says nothing about
    // the first.
    expect(result.current.viewTypes).toEqual(['unspecified', 'back']);
  });

  it('marks a photo the browser could not decode without removing it', () => {
    const { result } = renderHook(() => useSelectedImages());

    act(() => {
      result.current.add([png('a.png', { lastModified: 1 })]);
    });
    act(() => {
      result.current.markUndecodable(result.current.entries[0].id);
    });

    // Removing a file the user chose, on the strength of a failed preview,
    // would take the decision away from them.
    expect(result.current.entries[0].decodeFailed).toBe(true);
    expect(result.current.count).toBe(1);
  });

  it('empties the set and revokes what it held', () => {
    const { result } = renderHook(() => useSelectedImages());

    act(() => {
      result.current.add([
        png('a.png', { lastModified: 1 }),
        png('b.png', { lastModified: 2 }),
      ]);
    });
    act(() => {
      result.current.clear();
    });

    expect(result.current.entries).toEqual([]);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it('dismisses the refusals without touching the set', () => {
    const { result } = renderHook(() => useSelectedImages());

    act(() => {
      result.current.add([
        png('a.png', { lastModified: 1 }),
        new File(['x'], 'b.pdf', { type: 'application/pdf' }),
      ]);
    });
    act(() => {
      result.current.dismissRejections();
    });

    expect(result.current.rejections).toEqual([]);
    expect(result.current.count).toBe(1);
  });
});
