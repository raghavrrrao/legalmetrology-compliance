/**
 * Label-extraction client: what was read off a package, and nothing more.
 *
 * One inspection may carry several photographs of the same package - front,
 * back, a side panel, a close-up - and they are sent by repeating the `image`
 * part of one multipart body. They come back as **one** reading, not several,
 * because a packaged commodity declares different things on different panels
 * and the question "what does this package say" has one answer.
 *
 * Mirrors `POST /api/v1/extraction/` and the mappers in
 * `frontend/src/services/extractionService.js`. A reading is an observation
 * about a photograph; a verdict is a claim about a package under the Rules.
 * `compliance.ts` imports the mappers below and nothing here knows that
 * compliance exists - the same direction the backend runs.
 *
 * Maps the API's snake_case onto camelCase at the boundary and lets `ApiError`
 * propagate. It decides nothing.
 */

import { File } from 'expo-file-system';

import { ApiError, apiClient, type RequestOptions, type UploadFile } from './client';
import type {
  ExtractedField,
  ExtractedFieldWire,
  ExtractionResponseWire,
  ExtractionRun,
  ExtractionRunWire,
  InspectionImage,
  ProductClassification,
  ProductClassificationWire,
  ProductImage,
  ProductImageWire,
  RunImageWire,
} from '../types/api';

/**
 * Extraction runs inline on the backend, and a phone on a mobile network is
 * also uploading a multi-megabyte photograph first. The measured OCR median is
 * ~2.2 s with a recorded maximum over 3 s; the client's 15 s default is not
 * generous enough for a large photograph over a slow connection, and a timeout
 * there looks to the user exactly like a broken server.
 */
export const EXTRACTION_TIMEOUT_MS = 90000;

/**
 * Added to the timeout for each photograph after the first.
 *
 * The backend reads the set one photograph at a time in the same request, so
 * a three-image inspection genuinely takes about three times as long to upload
 * and read. Keeping the single-image timeout for a set would abort work that
 * was proceeding normally, and the user would see it as a broken server.
 *
 * Not a progress estimate and never shown: the app reports no ETA, because the
 * pipeline reports none.
 */
export const EXTRACTION_TIMEOUT_PER_EXTRA_IMAGE_MS = 60000;

export function extractionTimeoutFor(imageCount: number): number {
  return EXTRACTION_TIMEOUT_MS + Math.max(0, imageCount - 1) * EXTRACTION_TIMEOUT_PER_EXTRA_IMAGE_MS;
}

export function mapExtractedField(field: ExtractedFieldWire): ExtractedField {
  return {
    fieldKey: field.field_key,
    rawValue: field.raw_value ?? '',
    normalizedValue: field.normalized_value ?? null,
    confidence: typeof field.confidence === 'number' ? field.confidence : null,
    boundingBox: field.bounding_box ?? null,
    // Absent on a backend without image sets, and null when the source was not
    // recorded. Both map to null, which the UI reads as "not stated" - never
    // as "no photograph was involved".
    imageId: typeof field.image_id === 'string' ? field.image_id : null,
  };
}

export function mapImage(image: ProductImageWire | null | undefined): ProductImage | null {
  if (!image) {
    return null;
  }
  return {
    id: image.id,
    originalFilename: image.original_filename,
    imageFormat: image.image_format,
    width: image.width,
    height: image.height,
    sizeBytes: image.size_bytes,
    viewType: image.view_type,
    status: image.status,
  };
}

/**
 * The photographs of one inspection, in the order they were sent.
 *
 * Falls back to the single `image` the response also carries when the backend
 * sent no `images` key at all. That is the honest reading of an older backend:
 * it returned one photograph, so the set is that photograph - not an empty
 * set, which would make the screen say no images were checked.
 *
 * Entries with no usable `image` object are dropped rather than rendered with
 * blanks, and the positions are taken from the backend rather than from the
 * array index, because the position is the number a person is shown beside a
 * piece of evidence and the two must agree.
 */
export function mapInspectionImages(
  images: RunImageWire[] | null | undefined,
  fallback?: ProductImageWire | null,
): InspectionImage[] {
  if (Array.isArray(images) && images.length > 0) {
    return images
      .map((entry) => {
        const image = mapImage(entry?.image);
        if (!image) {
          return null;
        }
        return {
          position: typeof entry.position === 'number' ? entry.position : 0,
          status: entry.status ?? '',
          errorCode: entry.error_code ?? '',
          processingMs: typeof entry.processing_ms === 'number' ? entry.processing_ms : null,
          image,
        };
      })
      .filter((entry): entry is InspectionImage => entry !== null);
  }

  const single = mapImage(fallback);
  if (!single) {
    return [];
  }
  return [{ position: 1, status: single.status, errorCode: '', processingMs: null, image: single }];
}

/**
 * The classifier's observation, or null when none was made.
 *
 * Null is the ordinary case for a backend without the classifier (production
 * runs `tesseract` 0.3.0 at the time of writing; the classifier arrived in
 * 0.4.0), and it must be treated as "no classification", never as a category.
 * Anything that is not an object with a string `category` is treated the same
 * way, so a malformed value cannot be shown as a product type.
 */
export function mapProductClassification(
  value: ProductClassificationWire | null | undefined,
): ProductClassification | null {
  if (!value || typeof value !== 'object' || typeof value.category !== 'string') {
    return null;
  }
  return {
    category: value.category,
    subcategory: typeof value.subcategory === 'string' ? value.subcategory : null,
    confidence: typeof value.confidence === 'number' ? value.confidence : null,
    subcategoryConfidence:
      typeof value.subcategory_confidence === 'number' ? value.subcategory_confidence : null,
    evidence: Array.isArray(value.evidence)
      ? value.evidence.filter((item): item is string => typeof item === 'string')
      : [],
    categoryScores:
      value.category_scores && typeof value.category_scores === 'object' ? value.category_scores : {},
    classifierName: value.classifier_name ?? '',
    classifierVersion: value.classifier_version ?? '',
  };
}

export function mapExtractionRun(run: ExtractionRunWire | null | undefined): ExtractionRun | null {
  if (!run) {
    return null;
  }
  return {
    id: run.id,
    engineName: run.engine_name ?? '',
    engineVersion: run.engine_version ?? '',
    // Surfaced so the UI can say the pipeline read nothing. Presenting
    // placeholder output as a reading is the one thing a screen must not do.
    isPlaceholder: Boolean(run.is_placeholder),
    status: run.status ?? '',
    // Not the same question as `status`: this one says whether the label was
    // read well enough to be judged against at all.
    producedUsableOutput: Boolean(run.produced_usable_output),
    processingMs: typeof run.processing_ms === 'number' ? run.processing_ms : null,
    recognisedText: run.recognised_text || '',
    errorCode: run.error_code || '',
    errorMessage: run.error_message || '',
    fieldsRead: Array.isArray(run.fields_read) ? run.fields_read.map(mapExtractedField) : [],
    // The photographs this one reading was made from. Never several readings.
    images: mapInspectionImages(run.images),
    // Declarations the label named whose values could not be read. Kept
    // distinct from "not found": one asks for a better photograph, the other
    // is a possible contravention.
    unreadDeclarations: Array.isArray(run.unread_declarations)
      ? run.unread_declarations.map((item) => ({
          fieldKey: item.key ?? null,
          evidenceText: item.evidence_text ?? '',
          confidence: typeof item.confidence === 'number' ? item.confidence : null,
        }))
      : [],
    productClassification: mapProductClassification(run.product_classification),
  };
}

export interface ExtractLabelOptions extends Pick<RequestOptions, 'signal'> {
  /** A `ProductImage.ViewType` value. Omitted means `unspecified`. */
  viewType?: string;
}

export interface ExtractPackageOptions extends Pick<RequestOptions, 'signal'> {
  /**
   * A `ProductImage.ViewType` per photograph, positionally. Shorter than the
   * set leaves the rest `unspecified`; the value is never copied across,
   * because saying the first photograph is the front says nothing about the
   * second.
   */
  viewTypes?: (string | undefined)[];
}

/**
 * A multipart file part in the one shape both fetch implementations accept.
 *
 * Expo replaces the global `fetch` with `expo/fetch` (expo/src/winter/
 * runtime.native.ts), and its multipart encoder does not read React Native's
 * legacy `{ uri }` part - it throws "Unsupported FormDataPart implementation"
 * before any request is made, which the client could only report as a
 * network failure. What it does encode is a File-like object: `name` and
 * `type` become the part headers and `bytes()` supplies the content. React
 * Native's own fetch (restored by EXPO_PUBLIC_USE_RN_FETCH=1) reads `uri`,
 * `name` and `type` instead. Carrying all four keeps the upload working
 * under either.
 *
 * `name` and `type` are the validated values from `imageValidation.ts`, not
 * whatever the file on disk is called, because the backend checks the
 * extension and declared type of the part it receives before decoding it.
 */
export interface UploadPart {
  uri: string;
  name: string;
  type: string;
  bytes: () => Promise<Uint8Array>;
}

export function toUploadPart(file: UploadFile): UploadPart {
  // Read lazily, when the body is encoded, so building the form costs nothing
  // and a file that has vanished from the cache fails at upload time with a
  // real error rather than at selection time.
  const handle = new File(file.uri);
  return {
    uri: file.uri,
    name: file.name,
    type: file.type,
    bytes: () => handle.bytes(),
  };
}

/**
 * Build the multipart body for an upload of one or more photographs.
 *
 * **The `image` part is repeated, once per photograph**, which is the ordinary
 * multipart way to send several values under one name and is what the backend
 * reads. One photograph produces exactly the body this app has always sent.
 *
 * `view_type` is repeated alongside it and read positionally by the backend.
 * A photograph whose panel was not stated contributes an `unspecified` part
 * rather than being skipped - skipping one would shift every later view type
 * onto the wrong photograph, which is worse than saying nothing about any of
 * them.
 *
 * Exported so a test can check what is sent without a server: the field name
 * the backend reads, the number of parts, and each file part's `name` and
 * `type`, which the backend's validators check before decoding the bytes.
 * Content-Type is never set here: the fetch implementation generates the
 * boundary.
 */
export function buildUploadFormData(
  files: UploadFile | UploadFile[],
  viewTypes?: string | (string | undefined)[],
): FormData {
  const formData = new FormData();
  const list = Array.isArray(files) ? files : [files];
  const panels = Array.isArray(viewTypes) ? viewTypes : viewTypes === undefined ? [] : [viewTypes];

  list.forEach((file) => {
    // The DOM typings only know Blob; the runtime accepts the File-like part.
    formData.append('image', toUploadPart(file) as unknown as Blob);
  });

  // Only sent when at least one panel was actually stated, so an app that
  // names none goes on sending the body it always sent.
  if (panels.some((panel) => Boolean(panel))) {
    list.forEach((_file, index) => {
      formData.append('view_type', panels[index] || UNSPECIFIED_VIEW_TYPE);
    });
  }
  return formData;
}

/** The backend's `ProductImage.ViewType` default, used to pad the parts. */
export const UNSPECIFIED_VIEW_TYPE = 'unspecified';

/**
 * Upload one photograph and receive what was read off it.
 *
 * The single-photograph form of `extractPackage`, kept because most callers
 * and every existing test have exactly one photograph in hand. It delegates,
 * so one photograph takes the path a set of one does.
 *
 * No `categoryCode` parameter, deliberately: a category selects which rules
 * apply and no rule is consulted here. The endpoint does not accept one.
 *
 * @throws {ApiError}
 */
export async function extractLabel(
  file: UploadFile,
  options: ExtractLabelOptions = {},
): Promise<ExtractionRun & { image: ProductImage | null }> {
  const { viewType, ...requestOptions } = options;
  return extractPackage([file], { ...requestOptions, viewTypes: viewType ? [viewType] : undefined });
}

/**
 * Upload every photograph of one package and receive **one** reading of it.
 *
 * Not several readings presented together: the backend reads the set into one
 * `ExtractionRun`, so a declaration printed only on the back panel is a
 * declaration this reading contains. Each entry in `fieldsRead` carries the
 * `imageId` it was read from.
 *
 * The timeout grows with the set, because the backend reads the photographs
 * one after another inside the request. That is a real cost, not a guess about
 * progress - nothing here shows an estimate.
 *
 * @throws {ApiError}
 */
export async function extractPackage(
  files: UploadFile[],
  options: ExtractPackageOptions = {},
): Promise<ExtractionRun & { image: ProductImage | null }> {
  const { viewTypes, ...requestOptions } = options;

  if (files.length === 0) {
    // Guarded here rather than left to a 400, because an empty set is a bug in
    // the caller and the user should never be shown a server error for it.
    throw new ApiError('Add at least one photo of the package before checking it.', {
      status: 0,
      code: 'no_images',
    });
  }

  const data = await apiClient.upload<ExtractionResponseWire>(
    'extraction/',
    buildUploadFormData(files, viewTypes),
    { timeoutMs: extractionTimeoutFor(files.length), ...requestOptions },
  );

  const run = mapExtractionRun(data);
  if (!run || typeof run.id !== 'string' || !run.id) {
    // A 2xx with no run id is a body this client cannot act on. Failing here
    // is better than carrying an undefined id into the compliance request.
    throw new ApiError('The server returned an unexpected response.', {
      status: 200,
      code: 'unexpected_response',
    });
  }
  return {
    ...run,
    // Against an older backend the run carries no set, so the single image the
    // response does report becomes the set of one it always was.
    images: run.images.length > 0 ? run.images : mapInspectionImages(undefined, data.image),
    image: mapImage(data.image),
  };
}
