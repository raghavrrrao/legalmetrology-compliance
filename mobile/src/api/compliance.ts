/**
 * Compliance analysis client.
 *
 * Two calls, matching what the mobile flow uses:
 *
 *   evaluateExtractionRun()  POST /api/v1/compliance/          the two-step path
 *   fetchComplianceResult()  GET  /api/v1/compliance/<uuid>/   a stored result
 *
 * The one-shot `POST /api/v1/images/` and the history list are part of the
 * published API but not used by any mobile screen yet, so they are not wrapped
 * here - a client should not carry code with no caller.
 *
 * Nothing here decides anything. The verdict, its explanation and every finding
 * are computed by the deterministic engine in the backend; this module renames
 * keys. A compliance rule must never be implemented in JavaScript - a phone is
 * not where a legal determination can be audited.
 */

import { ApiError, apiClient, type RequestOptions } from './client';
import { mapExtractionRun, mapImage } from './extraction';
import type {
  AppliedDeclaration,
  AppliedDeclarationWire,
  ComplianceCheckWire,
  ComplianceEvaluationRequestWire,
  ComplianceResult,
  Finding,
  FindingWire,
  Violation,
  ViolationWire,
} from '../types/api';

function asNumberOrNull(value: unknown): number | null {
  return typeof value === 'number' ? value : null;
}

export function mapViolation(violation: ViolationWire): Violation {
  return {
    id: violation.id,
    ruleCode: violation.rule_code,
    legalReference: violation.legal_reference || '',
    severity: violation.severity ?? '',
    fieldKey: violation.field_key || '',
    message: violation.message ?? '',
    evidence: Array.isArray(violation.evidence)
      ? violation.evidence.map((item) => ({
          excerpt: item.excerpt || '',
          boundingBox: item.bounding_box ?? null,
          note: item.note || '',
        }))
      : [],
  };
}

/**
 * One rule's outcome: what was required, what was read, and what was concluded.
 *
 * Every optional field is normalised to a value the UI can render without
 * checking for `undefined` - except the two where absence is information:
 * `extractedConfidence` and `boundingBox` stay `null`, because "the engine did
 * not report one" is not zero and is not an origin.
 */
export function mapFinding(finding: FindingWire): Finding {
  return {
    id: finding.id,
    ruleCode: finding.rule_code,
    clause: finding.clause || '',
    title: finding.title || '',
    requirement: finding.requirement || '',
    legalReference: finding.legal_reference || '',
    legalSourceCitation: finding.legal_source_citation || '',
    checkType: finding.check_type || '',
    detectionMethod: finding.detection_method || '',
    severity: finding.severity || '',
    // FOUR-valued and passed through verbatim. `inconclusive` is not a soft
    // fail and `not_applicable` is not a pass; these are the two values the UI
    // must never round to another.
    status: finding.status,
    downgradedFromFailed: Boolean(finding.downgraded_from_failed),
    applicabilityNote: finding.applicability_note || '',
    fieldKey: finding.field_key || '',
    extractedRawValue: finding.extracted_raw_value || '',
    extractedNormalizedValue: finding.extracted_normalized_value ?? null,
    extractedConfidence: asNumberOrNull(finding.extracted_confidence),
    message: finding.message || '',
    evidenceExcerpt: finding.evidence_excerpt || '',
    boundingBox: finding.bounding_box ?? null,
    details: finding.details && typeof finding.details === 'object' ? finding.details : {},
    violationId: typeof finding.violation === 'number' ? finding.violation : null,
  };
}

export function mapDeclaration(declaration: AppliedDeclarationWire): AppliedDeclaration {
  return {
    code: declaration.code,
    name: declaration.name || declaration.code,
    answer: declaration.answer,
    answerDisplay: declaration.answer_display || '',
    source: declaration.source || '',
    sourceDisplay: declaration.source_display || '',
    note: declaration.note || '',
    statedBeforeThisCheck:
      typeof declaration.stated_before_this_check === 'boolean'
        ? declaration.stated_before_this_check
        : null,
  };
}

/**
 * Map a `ComplianceCheck` body.
 *
 * Throws `ApiError` (`unexpected_response`) when the body is not an object
 * carrying an id and a verdict, so a 2xx that is not a compliance result
 * surfaces as an error the screens already know how to show, rather than as a
 * blank result page.
 */
export function mapResult(data: ComplianceCheckWire | null | undefined): ComplianceResult {
  if (!data || typeof data !== 'object' || typeof data.id !== 'string' || typeof data.result !== 'string') {
    throw new ApiError('The server returned an unexpected response.', {
      status: 200,
      code: 'unexpected_response',
    });
  }

  // `findings` is an additive field. Against a backend that predates it the key
  // is absent entirely, which is a different thing from an empty list.
  const findingsReported = Array.isArray(data.findings);

  return {
    id: data.id,
    status: data.status ?? '',
    result: data.result,
    resultDisplay: data.result_display || '',
    summary: data.summary || '',
    engineVersion: data.engine_version || '',
    rulesEvaluated: asNumberOrNull(data.rules_evaluated),
    rulesPassed: asNumberOrNull(data.rules_passed),
    rulesFailed: asNumberOrNull(data.rules_failed),
    rulesInconclusive: asNumberOrNull(data.rules_inconclusive),
    // Counted separately from the three above, and it must stay that way. A
    // rule that did not govern this package examined nothing.
    rulesNotApplicable: asNumberOrNull(data.rules_not_applicable),
    processingMs: asNumberOrNull(data.processing_ms),
    completedAt: data.completed_at ?? null,
    productCategoryCode: data.product_category_code ?? null,
    productCategorySource: typeof data.product_category_source === 'string' ? data.product_category_source : null,
    applicabilityDeclarations: Array.isArray(data.applicability_declarations)
      ? data.applicability_declarations.map(mapDeclaration)
      : [],
    findingsReported,
    findings: findingsReported ? (data.findings as FindingWire[]).map(mapFinding) : [],
    violations: Array.isArray(data.violations) ? data.violations.map(mapViolation) : [],
    extraction: mapExtractionRun(data.extraction),
    image: mapImage(data.image),
  };
}

export interface EvaluateOptions extends Pick<RequestOptions, 'signal'> {
  /** A `ProductCategory.code`, when a person has stated one. Never inferred here. */
  categoryCode?: string;
  /** Facts about the goods, `{condition_code: yes|no|unknown}`. Optional. */
  declarations?: Record<string, 'yes' | 'no' | 'unknown'>;
}

/**
 * Evaluate a reading that already exists against the applicable rules.
 *
 * The second half of the two-step path. The photograph is **not** read again:
 * the verdict is drawn from the stored run. Repeatable against the same run id
 * - that is the intended way to re-check with a product type or a stated fact
 * without re-uploading - and each call creates a new stored result.
 *
 * `categoryCode` is sent only when a person supplied it. The classifier's
 * suggestion (`extraction.productClassification`) is never copied into this
 * request automatically; docs/api.md is explicit that a client must not fill
 * the field without a person confirming.
 *
 * @throws {ApiError}
 */
export async function evaluateExtractionRun(
  extractionRunId: string,
  options: EvaluateOptions = {},
): Promise<ComplianceResult> {
  const { categoryCode, declarations, ...requestOptions } = options;

  const body: ComplianceEvaluationRequestWire = { extraction_run_id: extractionRunId };
  // Omitted rather than sent blank when unknown. The backend treats an absent
  // category as "the commodity is not known" and says so in the result.
  if (categoryCode && categoryCode.trim()) {
    body.category_code = categoryCode.trim();
  }
  if (declarations && Object.keys(declarations).length > 0) {
    body.applicability_declarations = declarations;
  }

  return mapResult(await apiClient.post<ComplianceCheckWire>('compliance/', body, requestOptions));
}

/**
 * Fetch a previously computed result by id.
 *
 * @throws {ApiError} - including `not_found` for a result the caller does not
 *   own, which the backend deliberately makes indistinguishable from one that
 *   does not exist.
 */
export async function fetchComplianceResult(
  checkId: string,
  options: Pick<RequestOptions, 'signal'> = {},
): Promise<ComplianceResult> {
  return mapResult(await apiClient.get<ComplianceCheckWire>(`compliance/${checkId}/`, options));
}
