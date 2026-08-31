/**
 * Label-extraction client: what was read off a photograph, and nothing more.
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

/**
 * Extraction runs inline on the backend. The measured median is ~2.2 s on the
 * configured Tesseract pipeline with a recorded maximum over 3 s, so the
 * client's 15 s default is not generous enough for a large photograph on a slow
 * machine - and a timeout there looks to the user exactly like a broken server.
 */
export const EXTRACTION_TIMEOUT_MS = 60000;

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

/**
 * Upload a label photograph and receive what was read off it.
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

  const formData = new FormData();
  formData.append('image', file);
  if (viewType) {
    formData.append('view_type', viewType);
  }

  const data = await apiClient.upload('extraction/', formData, {
    timeoutMs: EXTRACTION_TIMEOUT_MS,
    ...requestOptions,
  });

  return { ...mapExtractionRun(data), image: mapImage(data.image) };
}
