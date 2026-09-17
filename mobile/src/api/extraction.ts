/**
 * Label-extraction client: what was read off a photograph, and nothing more.
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

import { ApiError, apiClient, type RequestOptions, type UploadFile } from './client';
import type {
  ExtractedField,
  ExtractedFieldWire,
  ExtractionResponseWire,
  ExtractionRun,
  ExtractionRunWire,
  ProductClassification,
  ProductClassificationWire,
  ProductImage,
  ProductImageWire,
} from '../types/api';

/**
 * Extraction runs inline on the backend, and a phone on a mobile network is
 * also uploading a multi-megabyte photograph first. The measured OCR median is
 * ~2.2 s with a recorded maximum over 3 s; the client's 15 s default is not
 * generous enough for a large photograph over a slow connection, and a timeout
 * there looks to the user exactly like a broken server.
 */
export const EXTRACTION_TIMEOUT_MS = 90000;

export function mapExtractedField(field: ExtractedFieldWire): ExtractedField {
  return {
    fieldKey: field.field_key,
    rawValue: field.raw_value ?? '',
    normalizedValue: field.normalized_value ?? null,
    confidence: typeof field.confidence === 'number' ? field.confidence : null,
    boundingBox: field.bounding_box ?? null,
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

/**
 * Build the multipart body for an upload.
 *
 * Exported so a test can check what is sent without a server: the field name
 * the backend reads (`image`), and the file part's `name` and `type`, which
 * the backend's validators check before decoding the bytes.
 */
export function buildUploadFormData(file: UploadFile, viewType?: string): FormData {
  const formData = new FormData();
  // React Native's FormData accepts { uri, name, type } and reads the file
  // itself. The DOM typings only know Blob, hence the cast.
  formData.append('image', file as unknown as Blob);
  if (viewType) {
    formData.append('view_type', viewType);
  }
  return formData;
}

/**
 * Upload a label photograph and receive what was read off it.
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

  const data = await apiClient.upload<ExtractionResponseWire>(
    'extraction/',
    buildUploadFormData(file, viewType),
    { timeoutMs: EXTRACTION_TIMEOUT_MS, ...requestOptions },
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
  return { ...run, image: mapImage(data.image) };
}
