/**
 * Compliance analysis client.
 *
 * Four calls, matching the four shapes the backend offers:
 *
 *   evaluateExtractionRun()  POST /api/v1/compliance/   the two-step path
 *   fetchComplianceResult()  GET  /api/v1/compliance/<uuid>/
 *   fetchComplianceHistory() GET  /api/v1/compliance/   the stored results
 *   analyseImage()           POST /api/v1/images/       the one-shot path
 *
 * The list and the detail endpoint return different shapes of the same records,
 * so they get different mappers: `mapResult` for the full trace, `mapHistoryRow`
 * for a row of history. A history row is not a thin `ComplianceResult` and is
 * deliberately not modelled as one - see `mapHistoryRow`.
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
 * @property {string} clause          the sub-rule, e.g. '6(1)(c)'; '' if unmapped
 * @property {string} title
 * @property {string} requirement     what the package must declare
 * @property {string} legalReference
 * @property {string} legalSourceCitation  the amending instrument, or ''
 * @property {string} checkType
 * @property {string} detectionMethod what evidence could settle it at all
 * @property {string} severity        triage ranking only, no legal weight
 * @property {'passed'|'failed'|'inconclusive'|'not_applicable'} status
 * @property {boolean} downgradedFromFailed
 * @property {string} applicabilityNote why it was applied, and what is unknown
 * @property {string} fieldKey
 * @property {string} extractedRawValue        the text as recognised
 * @property {object|null} extractedNormalizedValue  its interpretation, or null
 * @property {number|null} extractedConfidence  null means "not reported"
 * @property {string} message
 * @property {string} evidenceExcerpt
 * @property {object|null} boundingBox
 * @property {object} details
 * @property {number|null} violationId  the violation this became, or null
 */

/**
 * @typedef {object} AppliedDeclaration
 * @property {string} code
 * @property {string} name
 * @property {'yes'|'no'|'unknown'} answer
 * @property {string} answerDisplay
 * @property {string} source          submitter | reviewer | category
 * @property {string} sourceDisplay
 * @property {string} note
 * @property {boolean|null} statedBeforeThisCheck  null when it cannot be told
 */

/**
 * @typedef {object} ComplianceResult
 * @property {string} id
 * @property {'compliant'|'partially_compliant'|'non_compliant'|'review_required'} result
 * @property {string} resultDisplay
 * @property {string} summary
 * @property {string|null} productCategoryCode
 * @property {string|null} productCategorySource  submitter | reviewer | classifier, or null
 * @property {AppliedDeclaration[]} applicabilityDeclarations
 * @property {ApplicabilityAssessment|null} applicabilityAssessment
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
    // The clause of the Rules this concerns. Blank when the executable rule is
    // not mapped to the legal framework, which is a real state and not an
    // error - the UI says so rather than printing an empty label.
    clause: finding.clause || '',
    title: finding.title || '',
    requirement: finding.requirement || '',
    legalReference: finding.legal_reference || '',
    // The notification that last amended the clause. Blank is meaningful: the
    // clause stands as it was made. Never rendered as missing data.
    legalSourceCitation: finding.legal_source_citation || '',
    checkType: finding.check_type || '',
    // Anything other than ocr / cv / ocr_cv names evidence this pipeline does
    // not have - a physical weighing, a register, an e-commerce listing.
    detectionMethod: finding.detection_method || '',
    severity: finding.severity || '',
    // FOUR-valued and passed through verbatim. `inconclusive` is not a soft
    // fail and `not_applicable` is not a pass; these are the two values the UI
    // must never round to another.
    status: finding.status,
    downgradedFromFailed: Boolean(finding.downgraded_from_failed),
    // Why the rule was applied to this package and what could not be
    // established about whether it should have been. Not boilerplate: it
    // carries the caveat that applies to every result.
    applicabilityNote: finding.applicability_note || '',
    fieldKey: finding.field_key || '',
    // Both, and neither replaces the other: the raw text is what was
    // recognised, the normalised value is an interpretation of it.
    extractedRawValue: finding.extracted_raw_value || '',
    extractedNormalizedValue: finding.extracted_normalized_value ?? null,
    extractedConfidence: finding.extracted_confidence ?? null,
    message: finding.message || '',
    evidenceExcerpt: finding.evidence_excerpt || '',
    boundingBox: finding.bounding_box ?? null,
    details: finding.details ?? {},
    violationId: finding.violation ?? null,
  };
}

/**
 * One fact a person asserted about the package.
 *
 * The third kind of evidence in a result, and the UI must keep it apart from
 * the other two: an extracted field was *read off the photograph*, a finding is
 * what a rule *concluded*, and this is what somebody *said* about the goods.
 * Rendering an assertion as though it were a measurement is the specific
 * confusion this separate mapper exists to prevent.
 *
 * @returns {AppliedDeclaration}
 */
function mapDeclaration(declaration) {
  return {
    code: declaration.code,
    name: declaration.name || declaration.code,
    answer: declaration.answer,
    answerDisplay: declaration.answer_display || '',
    source: declaration.source || '',
    sourceDisplay: declaration.source_display || '',
    note: declaration.note || '',
    // Null stays null: "the check recorded no start time, so this could not be
    // compared" is not "yes", and the UI shows nothing rather than a claim.
    statedBeforeThisCheck:
      typeof declaration.stated_before_this_check === 'boolean'
        ? declaration.stated_before_this_check
        : null,
  };
}

/**
 * @typedef {object} ApplicabilityAssessment
 * @property {'confident'|'uncertain'|'unknown'|'failed'|string} status  the policy's reliability verdict, NOT a compliance state
 * @property {string} reason
 * @property {{name: string, version: string, confidence: number|null, evidence: string[]}} classifier
 * @property {{accepted: boolean, minConfidence: number|null, evaluation: string|null}} policy
 * @property {{proposed: string|null, proposedName: string|null, confidence: number|null, inEffect: string|null, inEffectSource: string|null, disposition: string, reason: string}} category
 * @property {{condition: string, name: string, proposedAnswer: string, confidence: number|null, basis: string, affects: string[], inEffect: string, inEffectSource: string|null, disposition: string, reason: string}[]} facts
 * @property {{kind: string, code: string|null, suggested: string|null, prompt: string, choices: {code: string, name: string}[]}[]} questions
 */

/**
 * The fourth kind of evidence on a result, and the one most easily mistaken
 * for the other three: what the label *classifier* proposed, with the
 * backend's verdict on how far that can be relied on. `status` is about the
 * classification's reliability for applicability - `confident` means the
 * backend's accepted policy established the category automatically,
 * `uncertain` means it is a suggestion for a person - and it must never be
 * shown as, or folded into, a compliance status. Null against a backend that
 * predates the field, which the UI treats as "nothing to show".
 *
 * @returns {ApplicabilityAssessment|null}
 */
export function mapAssessment(data) {
  if (!data || typeof data !== 'object' || typeof data.status !== 'string') {
    return null;
  }
  const category = data.category ?? {};
  return {
    status: data.status,
    reason: data.reason || '',
    classifier: {
      name: data.classifier?.name || '',
      version: data.classifier?.version || '',
      confidence: data.classifier?.confidence ?? null,
      evidence: Array.isArray(data.classifier?.evidence) ? data.classifier.evidence : [],
    },
    policy: {
      accepted: Boolean(data.policy?.accepted),
      minConfidence: data.policy?.min_confidence ?? null,
      evaluation: data.policy?.evaluation ?? null,
    },
    category: {
      proposed: category.proposed ?? null,
      proposedName: category.proposed_name ?? null,
      confidence: category.confidence ?? null,
      inEffect: category.in_effect ?? null,
      inEffectSource: category.in_effect_source ?? null,
      disposition: category.disposition || 'not_proposed',
      reason: category.reason || '',
    },
    facts: (Array.isArray(data.facts) ? data.facts : []).map((fact) => ({
      condition: fact.condition,
      name: fact.name || fact.condition,
      proposedAnswer: fact.proposed_answer || '',
      confidence: fact.confidence ?? null,
      basis: fact.basis || '',
      affects: Array.isArray(fact.affects) ? fact.affects : [],
      inEffect: fact.in_effect || 'unknown',
      inEffectSource: fact.in_effect_source ?? null,
      disposition: fact.disposition || 'not_proposed',
      reason: fact.reason || '',
    })),
    questions: (Array.isArray(data.questions) ? data.questions : []).map((question) => ({
      kind: question.kind,
      code: question.code ?? null,
      suggested: question.suggested ?? null,
      prompt: question.prompt || '',
      choices: Array.isArray(question.choices) ? question.choices : [],
    })),
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
    // Counted separately from the three above, and it must stay that way. A
    // rule that did not govern this package examined nothing; folding it into
    // `rulesPassed` would turn a set of exemptions into a clean bill of health.
    // Null against a backend that predates the count, which is not zero.
    rulesNotApplicable:
      typeof data.rules_not_applicable === 'number'
        ? data.rules_not_applicable
        : null,
    processingMs: data.processing_ms ?? null,
    completedAt: data.completed_at ?? null,
    productCategoryCode: data.product_category_code ?? null,
    // Who set the category - `submitter`, `reviewer` or `classifier`. Null
    // when there is no category, and against a backend that predates it.
    productCategorySource: data.product_category_source ?? null,
    applicabilityDeclarations: Array.isArray(data.applicability_declarations)
      ? data.applicability_declarations.map(mapDeclaration)
      : [],
    applicabilityAssessment: mapAssessment(data.applicability_assessment),
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
 * `declarations` are facts about the goods - "this package contains bidi",
 * "this package is imported" - that the Rules make decisive and that no
 * photograph can establish. They do **not** choose which rules run: the engine
 * still decides what each fact means, from conditions loaded out of the
 * verified legal framework. Send only codes served by
 * `fetchApplicabilityConditions`.
 *
 * @param {string} extractionRunId  as returned by `extractLabel`
 * @param {{categoryCode?: string, declarations?: Record<string,string>, signal?: AbortSignal}} [options]
 * @returns {Promise<ComplianceResult>}
 * @throws {import('./apiClient.js').ApiError}
 */
export async function evaluateExtractionRun(extractionRunId, options = {}) {
  const { categoryCode, declarations, ...requestOptions } = options;

  const body = { extraction_run_id: extractionRunId };
  // Omitted rather than sent blank when unknown. The backend treats an absent
  // category as "the commodity is not known" and says so in the result, which
  // is the honest answer; sending "" would mean the same thing less clearly.
  if (categoryCode) {
    body.category_code = categoryCode;
  }

  const stated = pruneUnansweredDeclarations(declarations);
  if (stated) {
    body.applicability_declarations = stated;
  }

  return mapResult(await apiClient.post('compliance/', body, requestOptions));
}

/**
 * Drop the questions nobody answered, keep every answer that was given.
 *
 * A form holds one entry per question, most of them unanswered. Sending those
 * is not wrong - the API treats `unknown` and an absent key identically - but
 * it puts a row in the database recording an answer of "don't know" for every
 * question the user skipped, which is noise on the result screen.
 *
 * **`unknown` chosen deliberately is kept.** It means "somebody was asked and
 * did not know", which is worth recording even though it has the same effect on
 * the engine as silence. What is dropped is the form's own empty state, which
 * is not an answer at all. Turning either of those into `no` would silently
 * assert a fact nobody stated, and is the one thing this function must never
 * do.
 *
 * Returns null when nothing was answered, so the caller omits the key entirely.
 */
function pruneUnansweredDeclarations(declarations) {
  if (!declarations || typeof declarations !== 'object') {
    return null;
  }

  const stated = {};
  for (const [code, answer] of Object.entries(declarations)) {
    if (typeof answer === 'string' && answer !== '') {
      stated[code] = answer;
    }
  }

  return Object.keys(stated).length > 0 ? stated : null;
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

/**
 * @typedef {object} ComplianceHistoryRow
 * @property {string} id                  the link to /result/<id>
 * @property {string} status              lifecycle of the evaluation itself
 * @property {string} result              the verdict
 * @property {string} resultDisplay       the verdict's label, from the backend
 * @property {string|null} createdAt      ISO 8601, the sort key
 * @property {string|null} completedAt
 * @property {string} engineVersion
 * @property {string|null} extractionRunId
 * @property {string|null} productCategoryCode
 * @property {number|null} findingsCount  null means "not reported"
 * @property {number|null} violationsCount
 */

/**
 * @typedef {object} ComplianceHistoryPage
 * @property {number|null} count      total stored results, null if not reported
 * @property {string|null} next       absolute URL of the next page, or null
 * @property {string|null} previous
 * @property {ComplianceHistoryRow[]} results
 */

/**
 * One row of inspection history.
 *
 * The list endpoint is deliberately a different, lighter shape than the detail
 * endpoint - no findings, no violations, no evidence, no reading - so this maps
 * only what a history row shows or navigates by. Nothing is filled in from
 * elsewhere: a row is not a partial `ComplianceResult` and must not be used as
 * one, which is why it gets its own mapper and its own typedef.
 *
 * The two counts stay `null` when the key is absent, exactly as
 * `extractedConfidence` does above: "the server did not report a count" is not
 * zero, and a row from a backend predating the counts must not claim that no
 * rule was examined. `status` and `result` are carried separately because the
 * backend keeps them separate - one says whether the evaluation ran, the other
 * says what it concluded - and collapsing them here would invent a verdict for
 * a check that never produced one.
 *
 * @returns {ComplianceHistoryRow}
 */
function mapHistoryRow(row) {
  return {
    id: row.id,
    status: row.status,
    result: row.result,
    resultDisplay: row.result_display || '',
    createdAt: row.created_at ?? null,
    completedAt: row.completed_at ?? null,
    engineVersion: row.engine_version || '',
    extractionRunId: row.extraction_run_id ?? null,
    productCategoryCode: row.product_category_code ?? null,
    findingsCount: typeof row.findings_count === 'number' ? row.findings_count : null,
    violationsCount:
      typeof row.violations_count === 'number' ? row.violations_count : null,
  };
}

/**
 * A page of history, with the pagination the caller needs to walk it.
 *
 * `next` and `previous` are passed through as the backend built them - absolute
 * URLs, or null at either end - and are the only way this app moves between
 * pages. Building `?page=n` here would hardcode a page size the server owns and
 * would silently break the first time it changes.
 *
 * `count` stays null rather than falling back to `results.length` when the key
 * is missing: the length of one page is not the number of stored results, and a
 * screen that printed it as a total would state a number nothing counted.
 *
 * @returns {ComplianceHistoryPage}
 */
function mapHistoryPage(data) {
  // Defensive rather than trusting: `results` drives a `.map` and a non-list
  // here would take the whole screen down over a malformed response.
  const results = Array.isArray(data?.results) ? data.results : [];

  return {
    count: typeof data?.count === 'number' ? data.count : null,
    next: data?.next ?? null,
    previous: data?.previous ?? null,
    results: results.map(mapHistoryRow),
  };
}

/**
 * List the compliance results already stored, newest first.
 *
 * `GET /api/v1/compliance/` - the history the Inspections screen draws. Each
 * row's `id` opens the full result at `/result/<id>`, which is still the only
 * place the trace lives; nothing on this endpoint is a substitute for it.
 *
 * Pass `url` to follow a `next` or `previous` from a page already fetched.
 * Absent, the first page is requested. The URL goes to `apiClient` unchanged -
 * it is absolute, and `apiClient` resolves it as given - so the sequence of
 * pages is the server's, not one this file reconstructed.
 *
 * @param {{url?: string|null, signal?: AbortSignal}} [options]
 * @returns {Promise<ComplianceHistoryPage>}
 * @throws {import('./apiClient.js').ApiError}
 */
export async function fetchComplianceHistory(options = {}) {
  const { url, ...requestOptions } = options;

  return mapHistoryPage(await apiClient.get(url || 'compliance/', requestOptions));
}
