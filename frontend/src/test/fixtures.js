/**
 * API response fixtures, in the shape the backend actually sends.
 *
 * Everything here is `snake_case` and matches the serializers in
 * `backend/apps/compliance/api/serializers.py` and
 * `backend/apps/extraction/api/serializers.py` field for field. That is the
 * point: a test that builds a camelCase object skips the mapping layer, which
 * is where a contract change would actually break the app.
 */

/**
 * An `ExtractionRun` as it is embedded in a compliance result.
 *
 * No `image` key: inside a `ComplianceCheck` the photograph is a sibling of the
 * run, not a child of it. `extractionBody` below adds it, because the response
 * to `POST /api/v1/extraction/` does.
 */
export function extractionRunBody(overrides = {}) {
  return {
    id: '99999999-8888-7777-6666-555555555555',
    engine_name: 'tesseract',
    engine_version: '0.2.0',
    is_placeholder: false,
    status: 'completed',
    produced_usable_output: true,
    processing_ms: 1100,
    recognised_text: 'Net Qty: 500 g\nMRP Rs. 149.00',
    error_code: '',
    error_message: '',
    fields_read: [
      {
        field_key: 'net_quantity',
        raw_value: 'Net Qty: 500 g',
        normalized_value: { value: 500, unit: 'g' },
        confidence: 0.91,
        bounding_box: { x: 40, y: 60, width: 200, height: 24 },
      },
    ],
    unread_declarations: [],
    ...overrides,
  };
}

/** The body of `POST /api/v1/extraction/`: the run, plus the image it read. */
export function extractionBody(overrides = {}) {
  return { ...extractionRunBody(), image: imageBody(), ...overrides };
}

export function imageBody(overrides = {}) {
  return {
    id: '77777777-6666-5555-4444-333333333333',
    original_filename: 'label.png',
    image_format: 'png',
    width: 800,
    height: 600,
    size_bytes: 12345,
    view_type: 'back',
    status: 'processed',
    ...overrides,
  };
}

/**
 * One entry of `findings[]`, with every field the serializer declares.
 *
 * Including the four that come from the legal framework rather than from the
 * executable rule - `clause`, `legal_source_citation`, `detection_method`,
 * `applicability_note`. A fixture that omitted them would let a component test
 * pass while the screen dropped the legal context on a real response, which is
 * exactly the failure that is invisible in a browser.
 */
export function findingBody(overrides = {}) {
  return {
    id: 1,
    rule_code: 'LM-PC-0001',
    clause: '6(1)(c)',
    title: 'Net quantity declaration',
    requirement: 'The package must declare its net quantity.',
    legal_reference: 'Rule 6(1)(e), LMPC Rules 2011',
    legal_source_citation: 'G.S.R. 202(E)',
    check_type: 'field_presence',
    detection_method: 'ocr',
    severity: 'major',
    status: 'passed',
    downgraded_from_failed: false,
    applicability_note:
      'Clause 6(1)(c) carries no applicability conditions, so it applies to every package in scope.\n\nApplicability rests on the product’s commodity category and on the facts declared for this submission.',
    field_key: 'net_quantity',
    extracted_raw_value: 'Net Qty: 500 g',
    extracted_normalized_value: { quantity: 500, unit: 'g', uncertain: false },
    extracted_confidence: 0.91,
    message: 'The declaration was found in the text read from this image.',
    evidence_excerpt: 'Net Qty: 500 g',
    bounding_box: { x: 40, y: 60, width: 200, height: 24 },
    details: {},
    violation: null,
    ...overrides,
  };
}

/** One entry of `applicability_declarations[]` on a compliance result. */
export function declarationBody(overrides = {}) {
  return {
    code: 'imported-product',
    name: 'Imported product or imported package',
    answer: 'no',
    answer_display: 'No',
    source: 'submitter',
    source_display: 'Declared by the submitter',
    note: '',
    stated_before_this_check: true,
    ...overrides,
  };
}

/** One entry of `GET /api/v1/compliance/applicability-conditions/`. */
export function applicabilityConditionBody(overrides = {}) {
  return {
    code: 'imported-product',
    name: 'Imported product or imported package',
    description: 'Whether this package was imported into India.',
    determination: 'user_declared',
    determination_note: 'Nothing on the label establishes import status.',
    scope: 'clause',
    answers: ['yes', 'no', 'unknown'],
    affects: [
      {
        clause: '6(1)(aa)',
        mode: 'requires',
        mode_display: 'Applies only to',
        note: 'Applies to imported products only.',
        rule_codes: ['LM-PC-0007'],
      },
    ],
    ...overrides,
  };
}

/** The body of `GET /api/v1/compliance/applicability-conditions/`. */
export function applicabilityBody(overrides = {}) {
  return {
    conditions: [
      applicabilityConditionBody(),
      applicabilityConditionBody({
        code: 'institutional-consumer',
        name: 'Package meant for an institutional consumer',
        description: 'Supplied to an institution rather than sold at retail.',
        scope: 'rules_scope',
        affects: [
          {
            clause: '3',
            mode: 'scope_gate',
            mode_display: 'Takes the package out of scope',
            note: 'Rule 3(c): Chapter II does not apply.',
            rule_codes: [],
          },
        ],
      }),
    ],
    answer_semantics: {
      yes: 'The fact holds for this package.',
      no: 'The fact does not hold.',
      unknown:
        'Not established. Identical in effect to sending nothing: the clause reaches REVIEW REQUIRED. It is never read as “no”.',
    },
    framework_loaded: true,
    ...overrides,
  };
}

/**
 * `applicability_assessment` on a compliance result, as the backend's
 * `auto_applicability.as_dict` shapes it. The default is the shipped
 * situation: the classifier committed, the policy accepts nothing, so the
 * category is a suggestion with one question open.
 */
export function assessmentBody(overrides = {}) {
  return {
    status: 'uncertain',
    reason:
      'The classifier tfidf-logreg 0.1.0 is not accepted for automatic use: no held-out evaluation on verified labels has established an operating point for it, so its category is a suggestion for a person to confirm.',
    classifier: {
      name: 'tfidf-logreg',
      version: '0.1.0',
      confidence: 0.72,
      evidence: ['signal: soap / bathing bar (typical of cosmetics-and-toiletries)'],
    },
    policy: { accepted: false, min_confidence: null, evaluation: null },
    category: {
      proposed: 'packaged-non-food',
      proposed_name: 'Packaged non-food',
      confidence: 0.72,
      in_effect: null,
      in_effect_source: null,
      disposition: 'needs_confirmation',
      reason:
        'The classifier tfidf-logreg 0.1.0 is not accepted for automatic use: no held-out evaluation on verified labels has established an operating point for it, so its category is a suggestion for a person to confirm.',
    },
    facts: [],
    evidence: assessmentEvidenceBody(),
    questions: [
      {
        kind: 'category',
        code: 'packaged-non-food',
        suggested: 'packaged-non-food',
        prompt: 'The label reads like packaged non-food. Is that right?',
        outcome:
          'Answering selects the requirements loaded for that product type and checks them against this same reading. The photograph is not uploaded or read again, and the answer is recorded as yours. Leaving it unanswered is a supported choice: the result then says the product type was not known rather than assuming one.',
        choices: [
          { code: 'packaged-food', name: 'Packaged food' },
          { code: 'packaged-non-food', name: 'Packaged non-food' },
        ],
      },
    ],
    ...overrides,
  };
}

/** `applicability_assessment.evidence` - what the reading offers for the suggestion. */
export function assessmentEvidenceBody(overrides = {}) {
  return {
    has_supporting_evidence: true,
    note: '',
    label_signals: [
      {
        phrase: 'soap / bathing bar',
        indicative_of: 'cosmetics-and-toiletries',
        snippet: '…dove beauty bathing bar moisturising cream…',
      },
      {
        phrase: 'for external use only',
        indicative_of: 'cosmetics-and-toiletries',
        snippet: '…milk for external use only keep out of reach…',
      },
    ],
    declared_fields: [{ field_key: 'net_quantity', value: 'Net Qty: 100 g' }],
    model_terms: ['bathing', 'bar'],
    ...overrides,
  };
}

/** One entry of `applicability_assessment.facts[]`: a subcategory's suggested condition. */
export function assessedFactBody(overrides = {}) {
  return {
    condition: 'cosmetics-and-toiletries',
    name: 'Soaps, shampoos, toothpastes and other cosmetics and toiletries',
    proposed_answer: 'yes',
    confidence: 0.56,
    basis: "The classifier's subcategory 'cosmetics-and-toiletries' corresponds to this condition.",
    affects: ['6(1)(d): exempts', '6(8): requires'],
    in_effect: 'unknown',
    in_effect_source: null,
    disposition: 'needs_confirmation',
    reason:
      'This fact exempts or triggers requirements, so it is never taken from the classifier. It stays unknown until a person confirms it.',
    ...overrides,
  };
}

/** The body of `POST /api/v1/compliance/` and `POST /api/v1/images/`. */
export function complianceBody(overrides = {}) {
  return {
    id: '11111111-2222-3333-4444-555555555555',
    status: 'completed',
    result: 'review_required',
    result_display: 'Review required',
    summary:
      'No compliance rules are loaded for this product’s category, so nothing was checked.',
    engine_version: '0.1.0',
    rules_evaluated: 0,
    rules_passed: 0,
    rules_failed: 0,
    rules_inconclusive: 0,
    rules_not_applicable: 0,
    processing_ms: 12,
    completed_at: '2026-08-30T12:00:00Z',
    product_category_code: null,
    product_category_source: null,
    applicability_declarations: [],
    applicability_assessment: assessmentBody(),
    violations: [],
    findings: [],
    extraction: extractionRunBody(),
    image: imageBody(),
    ...overrides,
  };
}

/**
 * One row of `GET /api/v1/compliance/`, with every field the list serializer
 * declares - and none of the fields it deliberately leaves out.
 *
 * Kept separate from `complianceBody` on purpose. The list and the detail
 * endpoint return different shapes of the same record, and a fixture that
 * blurred them would let a test pass against a response the API never sends.
 */
export function historyRowBody(overrides = {}) {
  return {
    id: '11111111-2222-3333-4444-555555555555',
    status: 'completed',
    result: 'review_required',
    result_display: 'Review required',
    created_at: '2026-08-30T12:00:00Z',
    completed_at: '2026-08-30T12:00:01Z',
    engine_version: '0.1.0',
    extraction_run_id: '99999999-8888-7777-6666-555555555555',
    product_category_code: null,
    findings_count: 4,
    violations_count: 2,
    ...overrides,
  };
}

/** The paginated envelope of `GET /api/v1/compliance/`. */
export function historyBody(overrides = {}) {
  const body = {
    count: 1,
    next: null,
    previous: null,
    results: [historyRowBody()],
    ...overrides,
  };
  // `count` follows the rows unless a test says otherwise, so a fixture with
  // three rows does not silently claim there is one.
  if (!('count' in overrides) && Array.isArray(body.results)) {
    body.count = body.results.length;
  }
  return body;
}
