/**
 * Compliance analysis client.
 *
 * Two calls: submit a photograph and get its result, or fetch a result again
 * by id. Follows the shape `healthService.js` set - a thin function per
 * endpoint that returns plain data and lets `ApiError` propagate - and maps
 * the API's snake_case onto camelCase here, so the rest of the frontend uses
 * one naming convention and a change to the API shape is contained in this
 * file.
 *
 * Nothing here decides anything. The verdict, its explanation and every
 * finding are computed by the deterministic engine in the backend; this module
 * renames keys. A compliance rule must never be implemented in JavaScript -
 * the browser is not where a legal determination can be audited.
 */

import { apiClient } from './apiClient.js';

/**
 * @typedef {object} ExtractedField
 * @property {string} fieldKey
 * @property {string} rawValue        exactly what OCR read
 * @property {object|null} normalizedValue  the interpretation, or null
 * @property {number|null} confidence
 * @property {object|null} boundingBox
 */

/**
 * @typedef {object} Violation
 * @property {number} id
 * @property {string} ruleCode
 * @property {string} legalReference
 * @property {string} severity        triage ranking only, no legal weight
 * @property {string} fieldKey
 * @property {string} message
 * @property {{excerpt: string, boundingBox: object|null, note: string}[]} evidence
 */

/**
 * @typedef {object} ComplianceResult
 * @property {string} id
 * @property {'compliant'|'partially_compliant'|'non_compliant'|'review_required'} result
 * @property {string} resultDisplay
 * @property {string} summary
 * @property {string|null} productCategoryCode
 * @property {Violation[]} violations
 * @property {object} extraction
 * @property {object} image
 */

function mapField(field) {
  return {
    fieldKey: field.field_key,
    rawValue: field.raw_value,
    normalizedValue: field.normalized_value ?? null,
    confidence: field.confidence ?? null,
    boundingBox: field.bounding_box ?? null,
  };
}

function mapViolation(violation) {
  return {
    id: violation.id,
    ruleCode: violation.rule_code,
    legalReference: violation.legal_reference || '',
    severity: violation.severity,
    fieldKey: violation.field_key || '',
    message: violation.message,
    evidence: (violation.evidence ?? []).map((item) => ({
      excerpt: item.excerpt || '',
      boundingBox: item.bounding_box ?? null,
      note: item.note || '',
    })),
  };
}

function mapExtraction(extraction) {
  if (!extraction) {
    return null;
  }
  return {
    id: extraction.id,
    engineName: extraction.engine_name,
    engineVersion: extraction.engine_version,
    // Surfaced so the UI can say the pipeline read nothing. Presenting
    // placeholder output as a reading is the one thing this screen must not do.
    isPlaceholder: extraction.is_placeholder,
    status: extraction.status,
    producedUsableOutput: extraction.produced_usable_output,
    processingMs: extraction.processing_ms ?? null,
    recognisedText: extraction.recognised_text || '',
    errorCode: extraction.error_code || '',
    errorMessage: extraction.error_message || '',
    fieldsRead: (extraction.fields_read ?? []).map(mapField),
    // Declarations the label named whose values could not be read. Kept
    // distinct from "not found": one asks for a better photograph, the other
    // is a possible contravention.
    unreadDeclarations: (extraction.unread_declarations ?? []).map((item) => ({
      fieldKey: item.key ?? null,
      evidenceText: item.evidence_text ?? '',
      confidence: item.confidence ?? null,
    })),
  };
}

/** @returns {ComplianceResult} */
function mapResult(data) {
  return {
    id: data.id,
    status: data.status,
    result: data.result,
    resultDisplay: data.result_display,
    summary: data.summary,
    engineVersion: data.engine_version,
    rulesEvaluated: data.rules_evaluated,
    rulesPassed: data.rules_passed,
    rulesFailed: data.rules_failed,
    rulesInconclusive: data.rules_inconclusive,
    processingMs: data.processing_ms ?? null,
    productCategoryCode: data.product_category_code ?? null,
    violations: (data.violations ?? []).map(mapViolation),
    extraction: mapExtraction(data.extraction),
    image: data.image
      ? {
          id: data.image.id,
          originalFilename: data.image.original_filename,
          imageFormat: data.image.image_format,
          width: data.image.width,
          height: data.image.height,
          sizeBytes: data.image.size_bytes,
          viewType: data.image.view_type,
          status: data.image.status,
        }
      : null,
  };
}

/**
 * Upload a label photograph and receive its compliance result.
 *
 * Synchronous on the backend: the response is the finished result, so there is
 * nothing to poll.
 *
 * @param {File} file
 * @param {{viewType?: string, categoryCode?: string, signal?: AbortSignal}} [options]
 * @returns {Promise<ComplianceResult>}
 * @throws {import('./apiClient.js').ApiError}
 */
export async function analyseImage(file, options = {}) {
  const { viewType, categoryCode, ...requestOptions } = options;

  const formData = new FormData();
  formData.append('image', file);
  if (viewType) {
    formData.append('view_type', viewType);
  }
  if (categoryCode) {
    formData.append('category_code', categoryCode);
  }

  const data = await apiClient.upload('images/', formData, {
    // Extraction runs inline and measures at a ~2.2 s median on the configured
    // Tesseract pipeline, with a recorded maximum over 3 s. The client default
    // of 15 s is not generous enough for a large photograph on a slow machine,
    // and a timeout here looks to the user exactly like a broken backend.
    timeoutMs: 60000,
    ...requestOptions,
  });

  return mapResult(data);
}

/**
 * Fetch a previously computed result by id.
 *
 * @param {string} checkId
 * @returns {Promise<ComplianceResult>}
 */
export async function fetchComplianceResult(checkId, options = {}) {
  const data = await apiClient.get(`compliance/${checkId}/`, options);
  return mapResult(data);
}
