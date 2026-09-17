/**
 * Client-side pre-checks on a picked photograph, before it is uploaded.
 *
 * These exist so the user gets an immediate, specific message instead of a
 * round trip that ends in a 400. **They are a courtesy, not the security
 * boundary.** The backend decodes every upload with Pillow and validates the
 * extension, declared content type, size, dimensions and pixel count
 * (`backend/apps/images/validators.py`) whatever this file concludes, and it
 * is the only authority on whether a file is acceptable. Nothing here makes a
 * rejected upload acceptable, and a picked file that passes here can still be
 * rejected there - which the screens handle as an ordinary validation error.
 *
 * The allowlist mirrors `backend/apps/images/constants.py`: JPEG, PNG and
 * WebP. It is an allowlist, never a denylist, for the same reason the
 * backend's is.
 */

import { MAX_UPLOAD_SIZE_BYTES, MAX_UPLOAD_SIZE_MB } from '../config/env';

/** Canonical format -> the MIME type and extension the upload is sent with. */
const FORMATS: Record<string, { mimeType: string; extension: string }> = {
  jpeg: { mimeType: 'image/jpeg', extension: '.jpg' },
  png: { mimeType: 'image/png', extension: '.png' },
  webp: { mimeType: 'image/webp', extension: '.webp' },
};

const FORMAT_BY_MIME: Record<string, string> = {
  'image/jpeg': 'jpeg',
  'image/jpg': 'jpeg',
  'image/png': 'png',
  'image/webp': 'webp',
};

const FORMAT_BY_EXTENSION: Record<string, string> = {
  '.jpg': 'jpeg',
  '.jpeg': 'jpeg',
  '.png': 'png',
  '.webp': 'webp',
};

/** Mirrors `MIN_IMAGE_DIMENSION` in the backend: nothing legible fits below it. */
export const MIN_IMAGE_DIMENSION = 32;

/**
 * What the picker handed back, in the subset this app reads. Every field but
 * `uri` may be missing: Android content providers and iOS limited-library
 * access both return assets with no name, no size or no MIME type.
 */
export interface PickedAsset {
  uri: string;
  fileName?: string | null;
  mimeType?: string | null;
  fileSize?: number | null;
  width?: number | null;
  height?: number | null;
}

/** A photograph that passed the pre-checks and is ready to preview and upload. */
export interface SelectedImage {
  /** Local file uri, used for both the preview and the multipart part. */
  uri: string;
  /** The filename the upload is sent with; always carries an allowed extension. */
  name: string;
  /** The MIME type the upload is sent with; always one of the allowed types. */
  type: string;
  /** Bytes, or null when the platform did not report a size. */
  sizeBytes: number | null;
  width: number | null;
  height: number | null;
}

export type ImageRejectionReason = 'unsupported_format' | 'too_large' | 'empty' | 'too_small';

export type ImageValidation =
  | { ok: true; image: SelectedImage }
  | { ok: false; reason: ImageRejectionReason; message: string };

function extensionOf(value: string | null | undefined): string {
  if (!value) {
    return '';
  }
  // Strip a query string or fragment a content uri might carry, then take the
  // last dotted segment of the final path component.
  const path = value.split(/[?#]/)[0];
  const base = path.split(/[\\/]/).pop() ?? '';
  const dot = base.lastIndexOf('.');
  return dot >= 0 ? base.slice(dot).toLowerCase() : '';
}

/**
 * Work out which allowed format a picked asset is, from what the platform
 * said about it. The declared MIME type is preferred; the filename, then the
 * uri, are fallbacks for platforms that report no MIME type at all.
 *
 * This is a claim, not a fact - the backend decodes the bytes to find out what
 * the file really is. It is enough to name the upload correctly and to catch
 * an obviously unsupported pick (a HEIC, a GIF) before it is sent.
 */
export function detectFormat(asset: PickedAsset): string | null {
  const mime = (asset.mimeType ?? '').toLowerCase().split(';')[0].trim();
  if (mime && FORMAT_BY_MIME[mime]) {
    return FORMAT_BY_MIME[mime];
  }
  const fromName = FORMAT_BY_EXTENSION[extensionOf(asset.fileName)];
  if (fromName) {
    return fromName;
  }
  const fromUri = FORMAT_BY_EXTENSION[extensionOf(asset.uri)];
  return fromUri ?? null;
}

function formatMegabytes(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Check a picked asset and shape it for upload.
 *
 * A size the platform did not report is not treated as zero: the upload is
 * attempted and the backend's own size check decides.
 */
export function validatePickedImage(asset: PickedAsset): ImageValidation {
  const format = detectFormat(asset);
  if (!format) {
    return {
      ok: false,
      reason: 'unsupported_format',
      message: 'This image format is not supported. Please use a JPEG, PNG or WebP photo.',
    };
  }

  if (typeof asset.fileSize === 'number') {
    if (asset.fileSize <= 0) {
      return {
        ok: false,
        reason: 'empty',
        message: 'The selected file is empty. Please choose another photo.',
      };
    }
    if (asset.fileSize > MAX_UPLOAD_SIZE_BYTES) {
      return {
        ok: false,
        reason: 'too_large',
        message:
          `This photo is ${formatMegabytes(asset.fileSize)}, which is larger than the `
          + `${MAX_UPLOAD_SIZE_MB} MB limit. Please take a smaller photo.`,
      };
    }
  }

  const width = typeof asset.width === 'number' && asset.width > 0 ? asset.width : null;
  const height = typeof asset.height === 'number' && asset.height > 0 ? asset.height : null;
  if ((width !== null && width < MIN_IMAGE_DIMENSION) || (height !== null && height < MIN_IMAGE_DIMENSION)) {
    return {
      ok: false,
      reason: 'too_small',
      message: 'This image is too small to read a label from. Please choose a larger photo.',
    };
  }

  const { mimeType, extension } = FORMATS[format];
  const baseName = (asset.fileName ?? '').split(/[\\/]/).pop() ?? '';
  const stem = baseName.replace(/\.[^.]*$/, '').replace(/[^A-Za-z0-9_-]+/g, '-').slice(0, 60);

  return {
    ok: true,
    image: {
      uri: asset.uri,
      // Always an allowed extension, whatever the platform called the file:
      // the backend checks the extension of the name it is sent.
      name: `${stem || 'label'}${extension}`,
      type: mimeType,
      sizeBytes: typeof asset.fileSize === 'number' ? asset.fileSize : null,
      width,
      height,
    },
  };
}
