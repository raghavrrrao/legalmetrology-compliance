/**
 * Client-side pre-checks on a picked photograph.
 *
 * The backend is the authority; these tests pin what the app rejects before
 * uploading and, more importantly, what it sends when it does upload - the
 * multipart name and type the backend's validators check first.
 */

import { detectFormat, validatePickedImage } from './imageValidation';
import { MAX_UPLOAD_SIZE_BYTES } from '../config/env';

describe('detectFormat', () => {
  it('prefers the declared MIME type', () => {
    expect(detectFormat({ uri: 'file:///a.bin', mimeType: 'image/png' })).toBe('png');
    expect(detectFormat({ uri: 'file:///a.bin', mimeType: 'image/jpg' })).toBe('jpeg');
    expect(detectFormat({ uri: 'file:///a.bin', mimeType: 'IMAGE/WEBP; charset=binary' })).toBe('webp');
  });

  it('falls back to the filename, then the uri', () => {
    expect(detectFormat({ uri: 'content://media/123', fileName: 'IMG_0001.JPG' })).toBe('jpeg');
    expect(detectFormat({ uri: 'file:///cache/ImagePicker/abc.png' })).toBe('png');
    expect(detectFormat({ uri: 'file:///cache/ImagePicker/abc.webp?x=1' })).toBe('webp');
  });

  it('returns null for anything outside the allowlist', () => {
    expect(detectFormat({ uri: 'file:///a.heic', mimeType: 'image/heic' })).toBeNull();
    expect(detectFormat({ uri: 'file:///a.gif' })).toBeNull();
    expect(detectFormat({ uri: 'content://media/123' })).toBeNull();
  });
});

describe('validatePickedImage', () => {
  it('accepts a JPEG and shapes it for upload', () => {
    const outcome = validatePickedImage({
      uri: 'file:///cache/ImagePicker/photo.jpg',
      fileName: 'photo.jpg',
      mimeType: 'image/jpeg',
      fileSize: 1_500_000,
      width: 3000,
      height: 4000,
    });

    expect(outcome).toEqual({
      ok: true,
      image: {
        uri: 'file:///cache/ImagePicker/photo.jpg',
        name: 'photo.jpg',
        type: 'image/jpeg',
        sizeBytes: 1_500_000,
        width: 3000,
        height: 4000,
      },
    });
  });

  it('gives an unnamed asset a name with an allowed extension', () => {
    // Android content providers and iOS limited-library picks have no name.
    // The backend checks the extension of the name it is sent.
    const outcome = validatePickedImage({ uri: 'content://media/external/images/123', mimeType: 'image/png' });

    expect(outcome.ok).toBe(true);
    if (outcome.ok) {
      expect(outcome.image.name).toBe('label.png');
      expect(outcome.image.type).toBe('image/png');
      expect(outcome.image.sizeBytes).toBeNull();
    }
  });

  it('normalises the extension to match the detected format', () => {
    const outcome = validatePickedImage({ uri: 'file:///a', fileName: 'scan.jpeg', mimeType: 'image/jpeg' });
    expect(outcome.ok && outcome.image.name).toBe('scan.jpg');
  });

  it('sanitises a filename before it is sent', () => {
    const outcome = validatePickedImage({ uri: 'file:///a', fileName: '../../weird name (1).png', mimeType: 'image/png' });
    expect(outcome.ok && outcome.image.name).toBe('weird-name-1-.png');
  });

  it('rejects an unsupported format before uploading', () => {
    const outcome = validatePickedImage({ uri: 'file:///a.heic', fileName: 'IMG_1.HEIC', mimeType: 'image/heic' });

    expect(outcome).toEqual({
      ok: false,
      reason: 'unsupported_format',
      message: expect.stringMatching(/JPEG, PNG or WebP/),
    });
  });

  it('rejects an oversized photo with the size in the message', () => {
    const outcome = validatePickedImage({ uri: 'file:///a.jpg', mimeType: 'image/jpeg', fileSize: MAX_UPLOAD_SIZE_BYTES + 1 });

    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.reason).toBe('too_large');
      expect(outcome.message).toMatch(/10 MB/);
    }
  });

  it('accepts a photo exactly at the limit', () => {
    expect(validatePickedImage({ uri: 'file:///a.jpg', mimeType: 'image/jpeg', fileSize: MAX_UPLOAD_SIZE_BYTES }).ok).toBe(true);
  });

  it('rejects an empty file', () => {
    const outcome = validatePickedImage({ uri: 'file:///a.jpg', mimeType: 'image/jpeg', fileSize: 0 });
    expect(outcome).toMatchObject({ ok: false, reason: 'empty' });
  });

  it('rejects an image too small to carry a label', () => {
    const outcome = validatePickedImage({ uri: 'file:///a.png', mimeType: 'image/png', width: 16, height: 16 });
    expect(outcome).toMatchObject({ ok: false, reason: 'too_small' });
  });

  it('does not treat an unreported size or dimensions as zero', () => {
    // The platform said nothing; the backend's own check decides.
    const outcome = validatePickedImage({ uri: 'file:///a.jpg', mimeType: 'image/jpeg', width: 0, height: 0 });
    expect(outcome.ok).toBe(true);
    if (outcome.ok) {
      expect(outcome.image.width).toBeNull();
      expect(outcome.image.height).toBeNull();
    }
  });
});
