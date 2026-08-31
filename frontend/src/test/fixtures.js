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

/** One entry of `findings[]`, with every field the serializer declares. */
export function findingBody(overrides = {}) {
  return {
    id: 1,
    rule_code: 'LM-PC-0001',
    title: 'Net quantity declaration',
    requirement: 'The package must declare its net quantity.',
    legal_reference: 'Rule 6(1)(e), LMPC Rules 2011',
    check_type: 'field_presence',
    severity: 'major',
    status: 'passed',
    downgraded_from_failed: false,
    field_key: 'net_quantity',
    extracted_confidence: 0.91,
    message: 'The declaration was found in the text read from this image.',
    evidence_excerpt: 'Net Qty: 500 g',
    bounding_box: { x: 40, y: 60, width: 200, height: 24 },
    details: {},
    violation: null,
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
    processing_ms: 12,
    completed_at: '2026-08-30T12:00:00Z',
    product_category_code: null,
    violations: [],
    findings: [],
    extraction: extractionRunBody(),
    image: imageBody(),
    ...overrides,
  };
}
