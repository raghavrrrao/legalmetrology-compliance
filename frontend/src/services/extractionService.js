/**
 * Label-extraction client: what was read off a package, and nothing more.
 *
 * One inspection may carry several photographs of the same package - front,
 * back, a side panel, a close-up - sent by repeating the `image` part of one
 * multipart body. They come back as **one** reading, not several, because a
 * packaged commodity declares different things on different panels and the
 * question "what does this package say" has one answer.
 *
 * Mirrors `POST /api/v1/extraction/`. A reading is an observation about a
 * photograph; a verdict is a claim about a package under the Rules. The backend
 * keeps those in separate apps and lets compliance import extraction but never
 * the reverse (see `apps/compliance/api/serializers.py`), and this module is the
 * frontend half of that split: `complianceService.js` imports the mappers below,
 * and nothing here knows that compliance exists.
 *
 * Like every service module, it maps the API's snake_case onto camelCase at the
 * boundary and lets `ApiError` propagate. It decides nothing.
 */

import { apiClient } from './apiClient.js';
import { MAX_INSPECTION_IMAGES } from '../config/env.js';

/**
 * Extraction runs inline on the backend. The measured median is ~2.2 s on the
 * configured Tesseract pipeline with a recorded maximum over 3 s, so the
 * client's 15 s default is not generous enough for a large photograph on a slow
 * machine - and a timeout there looks to the user exactly like a broken server.
 */
export const EXTRACTION_TIMEOUT_MS = 60000;

/**
 * Added to the timeout for each photograph after the first.
 *
 * The backend reads the set one photograph at a time inside the same request,
 * so a three-image inspection genuinely takes about three times as long.
 * Keeping the single-image allowance for a set would abort work that was
 * proceeding normally, and the user would read it as a broken server.
 *
 * Not a progress estimate, and never shown: the pipeline reports none.
 */
export const EXTRACTION_TIMEOUT_PER_EXTRA_IMAGE_MS = 45000;

/** @param {number} imageCount @returns {number} */
export function extractionTimeoutFor(imageCount) {
  const extra = Math.max(0, imageCount - 1);
  return EXTRACTION_TIMEOUT_MS + extra * EXTRACTION_TIMEOUT_PER_EXTRA_IMAGE_MS;
}

/**
 * @typedef {object} ExtractedField
 * @property {string} fieldKey
 * @property {string} rawValue        exactly what the engine read
 * @property {object|null} normalizedValue  the interpretation, or null
 * @property {number|null} confidence null means "not reported", never zero
 * @property {{x: number, y: number, width: number, height: number}|null} boundingBox
 */

/** @returns {ExtractedField} */
export function mapExtractedField(field) {
  return {
    fieldKey: field.field_key,
    rawValue: field.raw_value,
    normalizedValue: field.normalized_value ?? null,
    confidence: field.confidence ?? null,
    boundingBox: field.bounding_box ?? null,
    // Which photograph of the package this was read from. Absent on a backend
    // without image sets, and null when the source was not recorded; both map
    // to null, which the UI reads as "not stated" - never as "no photograph
    // was involved".
    imageId: typeof field.image_id === 'string' ? field.image_id : null,
  };
}

/**
 * The photograph a reading or a result is about.
 *
 * There is no URL here because the API does not expose one - every field is a
 * fact measured from the bytes during validation. A screen that wants to show
 * the image shows the `File` the user selected, and uses `width`/`height` from
 * here as the coordinate space that bounding boxes are expressed in.
 */
export function mapImage(image) {
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
 * @typedef {object} InspectionImage
 * @property {number} position   1-based, and the number a person is shown
 * @property {string} status     this photograph's own outcome, not the run's
 * @property {string} errorCode
 * @property {string} errorMessage
 * @property {number|null} processingMs
 * @property {object} image      the stored photograph's measured facts
 */

/**
 * The photographs of one inspection, in the order they were sent.
 *
 * Falls back to the single `image` the response also carries when the backend
 * sent no `images` key at all. That is the honest reading of an older backend:
 * it returned one photograph, so the set is that photograph - not an empty
 * set, which would make a screen say no images were checked.
 *
 * Positions come from the backend rather than from the array index, because
 * the position is the number shown beside a piece of evidence and the two must
 * agree. An entry with no usable image object is dropped rather than rendered
 * with blanks.
 *
 * @returns {InspectionImage[]}
 */
export function mapInspectionImages(images, fallback) {
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
          errorMessage: entry.error_message ?? '',
          processingMs: entry.processing_ms ?? null,
          image,
        };
      })
      .filter(Boolean);
  }

  const single = mapImage(fallback);
  if (!single) {
    return [];
  }
  return [
    {
      position: 1,
      status: single.status,
      errorCode: '',
      errorMessage: '',
      processingMs: null,
      image: single,
    },
  ];
}

/**
 * @typedef {object} ExtractionRun
 * @property {string} id                  pass this to the compliance endpoint
 * @property {string} engineName
 * @property {string} engineVersion
 * @property {boolean} isPlaceholder      true means no recognition happened
 * @property {string} status              completed | empty | failed
 * @property {boolean} producedUsableOutput
 * @property {number|null} processingMs
 * @property {string} recognisedText
 * @property {ExtractedField[]} fieldsRead
 */
export function mapExtractionRun(run) {
  if (!run) {
    return null;
  }
  return {
    id: run.id,
    engineName: run.engine_name,
    engineVersion: run.engine_version,
    // Surfaced so the UI can say the pipeline read nothing. Presenting
    // placeholder output as a reading is the one thing this screen must not do.
    isPlaceholder: run.is_placeholder,
    status: run.status,
    // Not the same question as `status`: this one says whether the label was
    // read well enough to be judged against at all. A client must branch on it
    // before treating an absent declaration as absent from the *package*
    // rather than from the *photograph*.
    producedUsableOutput: run.produced_usable_output,
    processingMs: run.processing_ms ?? null,
    recognisedText: run.recognised_text || '',
    errorCode: run.error_code || '',
    errorMessage: run.error_message || '',
    fieldsRead: (run.fields_read ?? []).map(mapExtractedField),
    // The photographs this one reading was made from. Never several readings.
    images: mapInspectionImages(run.images),
    // Declarations the label named whose values could not be read. Kept
    // distinct from "not found": one asks for a better photograph, the other
    // is a possible contravention.
    unreadDeclarations: (run.unread_declarations ?? []).map((item) => ({
      fieldKey: item.key ?? null,
      evidenceText: item.evidence_text ?? '',
      confidence: item.confidence ?? null,
    })),
  };
}

/** The backend's `ProductImage.ViewType` default, used to pad the parts. */
export const UNSPECIFIED_VIEW_TYPE = 'unspecified';

/**
 * Build the multipart body for an upload of one or more photographs.
 *
 * **The `image` part is repeated, once per photograph.** That is the ordinary
 * multipart way to send several values under one name and is exactly what the
 * backend reads (`docs/api.md`, "Several photographs, one inspection"). One
 * photograph produces precisely the body this client has always sent.
 *
 * `view_type` is repeated alongside it and read positionally by the backend. A
 * photograph whose panel was not stated contributes an `unspecified` part
 * rather than being skipped - skipping one would shift every later view type
 * onto the wrong photograph, which is worse than saying nothing about any of
 * them. The parts are omitted entirely when no panel was stated at all, so a
 * caller that names none sends the body it always sent.
 *
 * Exported so a test can assert on what is sent without a server.
 *
 * @param {File[]} files
 * @param {(string|undefined)[]} [viewTypes] positional, one per file
 * @returns {FormData}
 */
export function buildUploadFormData(files, viewTypes = []) {
  const formData = new FormData();
  const list = Array.isArray(files) ? files : [files];
  const panels = Array.isArray(viewTypes) ? viewTypes : [viewTypes];

  for (const file of list) {
    formData.append('image', file);
  }

  const stated = panels.some(
    (panel) => Boolean(panel) && panel !== UNSPECIFIED_VIEW_TYPE,
  );
  if (stated) {
    list.forEach((_file, index) => {
      formData.append('view_type', panels[index] || UNSPECIFIED_VIEW_TYPE);
    });
  }
  return formData;
}

/**
 * Upload one photograph and receive what was read off it.
 *
 * The single-photograph form of `extractPackage`, kept because callers that
 * hold exactly one file should not have to wrap it. It delegates, so one
 * photograph takes the path a set of one does.
 *
 * No `categoryCode` parameter, deliberately: a category selects which rules
 * apply and no rule is consulted here. The endpoint does not accept one.
 *
 * @param {File} file
 * @param {{viewType?: string, signal?: AbortSignal}} [options]
 * @returns {Promise<ExtractionRun & {image: object|null}>}
 * @throws {import('./apiClient.js').ApiError}
 */
export async function extractLabel(file, options = {}) {
  const { viewType, ...requestOptions } = options;
  return extractPackage([file], {
    ...requestOptions,
    viewTypes: viewType ? [viewType] : undefined,
  });
}

/**
 * Upload every photograph of one package and receive **one** reading of it.
 *
 * Not several readings presented together: the backend reads the set into one
 * `ExtractionRun`, so a declaration printed only on the back panel is a
 * declaration this reading contains. Each entry in `fieldsRead` carries the
 * `imageId` it was read from.
 *
 * @param {File[]} files in the order they will be positioned
 * @param {{viewTypes?: (string|undefined)[], signal?: AbortSignal}} [options]
 * @returns {Promise<ExtractionRun & {image: object|null}>}
 * @throws {import('./apiClient.js').ApiError}
 */
export async function extractPackage(files, options = {}) {
  const { viewTypes, ...requestOptions } = options;
  const list = (Array.isArray(files) ? files : [files]).filter(Boolean);

  if (list.length === 0) {
    // Guarded here rather than left to a 400: an empty set is a bug in the
    // caller, and the user should never be shown a server error for one.
    throw new RangeError('An inspection needs at least one photograph.');
  }
  if (list.length > MAX_INSPECTION_IMAGES) {
    // Also guarded before the request, because uploading several megabytes to
    // be told the count was wrong is a poor way to learn it.
    throw new RangeError(
      `An inspection may carry at most ${MAX_INSPECTION_IMAGES} photographs.`,
    );
  }

  const data = await apiClient.upload(
    'extraction/',
    buildUploadFormData(list, viewTypes),
    { timeoutMs: extractionTimeoutFor(list.length), ...requestOptions },
  );

  const run = mapExtractionRun(data);
  return {
    ...run,
    // Against an older backend the run carries no set, so the single image the
    // response does report becomes the set of one it always was.
    images:
      run.images.length > 0
        ? run.images
        : mapInspectionImages(undefined, data.image),
    image: mapImage(data.image),
  };
}
