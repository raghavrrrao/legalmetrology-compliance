/**
 * Compliance analysis client.
 *
 * Three calls, matching the three shapes the backend offers:
 *
 *   evaluateExtractionRun()  POST /api/v1/compliance/   the two-step path
 *   fetchComplianceResult()  GET  /api/v1/compliance/<uuid>/
 *   analyseImage()           POST /api/v1/images/       the one-shot path
 *
 * Follows the shape `healthService.js` set - a thin function per endpoint that
 * returns plain data and lets `ApiError` propagate - and maps the API's
 * snake_case onto camelCase here, so the rest of the frontend uses one naming
 * convention and a change to the API shape is contained in this file.
 *
 * The reading is not described here. `mapExtractionRun` and its parts live in
 * `extractionService.js` with the endpoint that owns them, and are imported
 * below, so the reading inside a compliance result is mapped by exactly the
 * same code as the reading returned on its own. That direction matters beyond
 * tidiness, and it is the direction the backend runs too: compliance may depend
 * on extraction, because a finding is made *from* a reading; extraction must
 * never depend on compliance, or a reading starts to be shaped by what a rule
 * wants it to say.
 *
 * Nothing here decides anything. The verdict, its explanation and every finding
 * are computed by the deterministic engine in the backend; this module renames
 * keys. A compliance rule must never be implemented in JavaScript - the browser
 * is not where a legal determination can be audited.
 */

import { apiClient } from './apiClient.js';
import {
  EXTRACTION_TIMEOUT_MS,
  mapExtractionRun,
  mapImage,
} from './extractionService.js';

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
 * @typedef {object} Finding
 * @property {number} id
 * @property {string} ruleCode
 * @property {string} title
 * @property {string} requirement     what the package must declare
 * @property {string} legalReference
 * @property {string} checkType
 * @property {string} severity        triage ranking only, no legal weight
 * @property {'passed'|'failed'|'inconclusive'} status
 * @property {boolean} downgradedFromFailed
 * @property {string} fieldKey
 * @property {number|null} extractedConfidence  null means "not reported"
 * @property {string} message
 * @property {string} evidenceExcerpt
 * @property {object|null} boundingBox
 * @property {object} details
 * @property {number|null} violationId  the violation this became, or null
 */

/**
 * @typedef {object} ComplianceResult
 * @property {string} id
 * @property {'compliant'|'partially_compliant'|'non_compliant'|'review_required'} result
 * @property {string} resultDisplay
 * @property {string} summary
 * @property {string|null} productCategoryCode
 * @property {Finding[]} findings
 * @property {boolean} findingsReported  false against a backend with no findings[]
 * @property {Violation[]} violations
 * @property {object|null} extraction
 * @property {object|null} image
 */

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

/**
 * One rule's outcome: what was required, what was read, and what was concluded.
 *
 * Every optional field is normalised to a value the UI can render without
 * checking for `undefined` - except the two where absence is information:
 * `extractedConfidence` and `boundingBox` stay `null`, because "the engine did
 * not report one" is not zero and is not an origin.
 *
 * @returns {Finding}
 */
function mapFinding(finding) {
  return {
    id: finding.id,
    ruleCode: finding.rule_code,
    title: finding.title || '',
    requirement: finding.requirement || '',
    legalReference: finding.legal_reference || '',
    checkType: finding.check_type || '',
    severity: finding.severity || '',
    // Three-valued and passed through verbatim. `inconclusive` is not a soft
    // fail, and this is the one value the UI must never round to another.
    status: finding.status,
    downgradedFromFailed: Boolean(finding.downgraded_from_failed),
    fieldKey: finding.field_key || '',
    extractedConfidence: finding.extracted_confidence ?? null,
    message: finding.message || '',
    evidenceExcerpt: finding.evidence_excerpt || '',
    boundingBox: finding.bounding_box ?? null,
    details: finding.details ?? {},
    violationId: finding.violation ?? null,
  };
}

/**
 * @param {object} data the `ComplianceCheck` body
 * @returns {ComplianceResult}
 */
function mapResult(data) {
  // `findings` is an additive field. Against a backend that predates it the key
  // is absent entirely, which is a different thing from an empty list: the
  // first means "this server does not report per-rule outcomes", the second
  // means "no rule was examined". The UI says something different for each, so
  // the distinction is carried rather than flattened here.
  const findingsReported = Array.isArray(data.findings);

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
    completedAt: data.completed_at ?? null,
    productCategoryCode: data.product_category_code ?? null,
    findingsReported,
    findings: findingsReported ? data.findings.map(mapFinding) : [],
    violations: (data.violations ?? []).map(mapViolation),
    extraction: mapExtractionRun(data.extraction),
    image: mapImage(data.image),
  };
}

/**
 * Evaluate a reading that already exists against the applicable rules.
 *
 * The second half of the two-step path. The photograph is **not** read again:
 * the verdict is drawn from the stored run, so the declarations the user was
 * shown and the declarations the findings cite are the same ones.
 *
 * Returns 201 rather than 200 on the wire because an evaluation is a new
 * record; there is nothing for a caller to do about that but not treat a
 * repeated call as free.
 *
 * @param {string} extractionRunId  as returned by `extractLabel`
 * @param {{categoryCode?: string, signal?: AbortSignal}} [options]
 * @returns {Promise<ComplianceResult>}
 * @throws {import('./apiClient.js').ApiError}
 */
export async function evaluateExtractionRun(extractionRunId, options = {}) {
  const { categoryCode, ...requestOptions } = options;

  const body = { extraction_run_id: extractionRunId };
  // Omitted rather than sent blank when unknown. The backend treats an absent
  // category as "the commodity is not known" and says so in the result, which
  // is the honest answer; sending "" would mean the same thing less clearly.
  if (categoryCode) {
    body.category_code = categoryCode;
  }

  return mapResult(await apiClient.post('compliance/', body, requestOptions));
}

/**
 * Fetch a previously computed result by id.
 *
 * Exists so a result survives a page reload and can be sent to a reviewer as a
 * link - see `ResultPage`.
 *
 * @param {string} checkId
 * @returns {Promise<ComplianceResult>}
 */
export async function fetchComplianceResult(checkId, options = {}) {
  return mapResult(await apiClient.get(`compliance/${checkId}/`, options));
}

/**
 * Upload a label photograph and receive its compliance result in one call.
 *
 * The one-shot path, retained because the endpoint is part of the published API
 * and a caller that wants only the verdict should not have to make two
 * requests. The scan screen does not use it: it needs the reading on screen
 * before any determination is offered, which is what the two-step path is for.
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
    timeoutMs: EXTRACTION_TIMEOUT_MS,
    ...requestOptions,
  });

  return mapResult(data);
}
