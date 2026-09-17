/**
 * API response fixtures, in the shape the backend actually sends.
 *
 * Everything here is `snake_case` and matches the serializers in
 * `backend/apps/compliance/api/serializers.py` and
 * `backend/apps/extraction/api/serializers.py` field for field, and the
 * examples in docs/api.md. That is the point: a test that builds a camelCase
 * object skips the mapping layer, which is where a contract change would
 * actually break the app. The same fixtures exist for the web client in
 * `frontend/src/test/fixtures.js`.
 */

import * as ImagePicker from 'expo-image-picker';

import type {
  ComplianceCheckWire,
  ExtractionResponseWire,
  ExtractionRunWire,
  FindingWire,
  ProductClassificationWire,
  ProductImageWire,
} from '../src/types/api';
import type { SelectedImage } from '../src/services/imageValidation';

export const RUN_ID = '99999999-8888-7777-6666-555555555555';
export const CHECK_ID = '11111111-2222-3333-4444-555555555555';
export const IMAGE_ID = '77777777-6666-5555-4444-333333333333';

export function imageBody(overrides: Partial<ProductImageWire> = {}): ProductImageWire {
  return {
    id: IMAGE_ID,
    original_filename: 'label.jpg',
    image_format: 'jpeg',
    width: 1600,
    height: 1200,
    size_bytes: 234567,
    view_type: 'unspecified',
    status: 'processed',
    ...overrides,
  };
}

/** The example in docs/api.md under `POST /api/v1/extraction/`. */
export function classificationBody(
  overrides: Partial<ProductClassificationWire> = {},
): ProductClassificationWire {
  return {
    category: 'packaged-food',
    subcategory: 'health-supplement',
    confidence: 0.7232,
    subcategory_confidence: 0.5517,
    evidence: ['signal: ingredients (typical of packaged-food)'],
    category_scores: { 'packaged-food': 0.7232, 'packaged-non-food': 0.2768 },
    subcategory_scores: { 'general-food': 0.1715, 'health-supplement': 0.5517 },
    classifier_name: 'tfidf-logreg',
    classifier_version: '0.1.0',
    ...overrides,
  };
}

/**
 * An `ExtractionRun` as it is embedded in a compliance result. No `image`
 * key: inside a `ComplianceCheck` the photograph is a sibling of the run.
 */
export function extractionRunBody(overrides: Partial<ExtractionRunWire> = {}): ExtractionRunWire {
  return {
    id: RUN_ID,
    engine_name: 'tesseract',
    engine_version: '0.4.0',
    is_placeholder: false,
    status: 'completed',
    produced_usable_output: true,
    processing_ms: 2202,
    recognised_text: 'Net Qty: 500 g\nMRP Rs. 149.00 (incl. of all taxes)',
    error_code: '',
    error_message: '',
    fields_read: [
      {
        field_key: 'net_quantity',
        raw_value: 'Net Qty: 500 g',
        normalized_value: { quantity: 500, unit: 'g', uncertain: false },
        confidence: 0.87,
        bounding_box: { x: 4, y: 4, width: 300, height: 18 },
      },
      {
        field_key: 'mrp',
        raw_value: 'MRP Rs. 149.00 (incl. of all taxes)',
        normalized_value: { amount: 149, currency: 'INR', inclusive_of_taxes: true },
        confidence: 0.91,
        bounding_box: null,
      },
    ],
    unread_declarations: [],
    product_classification: classificationBody(),
    ...overrides,
  };
}

/** The body of `POST /api/v1/extraction/`: the run, plus the image it read. */
export function extractionBody(overrides: Partial<ExtractionResponseWire> = {}): ExtractionResponseWire {
  return { ...extractionRunBody(), image: imageBody(), ...overrides };
}

export function findingBody(overrides: Partial<FindingWire> = {}): FindingWire {
  return {
    id: 1,
    rule_code: 'LMPC-NET-QTY-001',
    clause: '6(1)(d)',
    title: 'Net quantity declaration',
    requirement: 'The net quantity in standard units must be declared on the package.',
    legal_reference: 'Rule 6(1)(d), Legal Metrology (Packaged Commodities) Rules, 2011',
    legal_source_citation: '',
    check_type: 'field_present',
    detection_method: 'ocr',
    severity: 'high',
    status: 'passed',
    downgraded_from_failed: false,
    applicability_note: 'Applied because the package is declared as packaged food.',
    field_key: 'net_quantity',
    extracted_raw_value: 'Net Qty: 500 g',
    extracted_normalized_value: { quantity: 500, unit: 'g' },
    extracted_confidence: 0.87,
    message: 'A net quantity of 500 g was declared.',
    evidence_excerpt: 'Net Qty: 500 g',
    bounding_box: { x: 4, y: 4, width: 300, height: 18 },
    details: {},
    violation: null,
    ...overrides,
  };
}

/** A `ComplianceCheck`, as `POST /api/v1/compliance/` returns it. */
export function complianceBody(overrides: Partial<ComplianceCheckWire> = {}): ComplianceCheckWire {
  return {
    id: CHECK_ID,
    status: 'completed',
    result: 'partially_compliant',
    result_display: 'Partially compliant',
    summary: 'One requirement was not met and one could not be decided from this photograph.',
    engine_version: '1.3.0',
    rules_evaluated: 4,
    rules_passed: 2,
    rules_failed: 1,
    rules_inconclusive: 1,
    rules_not_applicable: 1,
    processing_ms: 41,
    completed_at: '2026-09-16T10:00:00Z',
    product_category_code: 'packaged-food',
    product_category_source: 'submitter',
    applicability_declarations: [],
    violations: [
      {
        id: 10,
        rule_code: 'LMPC-MFG-DATE-001',
        legal_reference: 'Rule 6(1)(c)',
        severity: 'high',
        field_key: 'manufacture_date',
        message: 'No month and year of manufacture was found on the label.',
        evidence: [{ excerpt: 'Net Qty: 500 g MRP Rs. 149.00', bounding_box: null, note: 'Text read from the label' }],
      },
    ],
    findings: [
      findingBody(),
      findingBody({
        id: 2,
        rule_code: 'LMPC-MRP-001',
        clause: '6(1)(e)',
        title: 'Retail sale price declaration',
        field_key: 'mrp',
        extracted_raw_value: 'MRP Rs. 149.00 (incl. of all taxes)',
        message: 'A retail sale price inclusive of all taxes was declared.',
        evidence_excerpt: 'MRP Rs. 149.00 (incl. of all taxes)',
        extracted_confidence: 0.91,
      }),
      findingBody({
        id: 3,
        rule_code: 'LMPC-MFG-DATE-001',
        clause: '6(1)(c)',
        title: 'Month and year of manufacture',
        field_key: 'manufacture_date',
        status: 'failed',
        extracted_raw_value: '',
        extracted_normalized_value: null,
        extracted_confidence: null,
        message: 'No month and year of manufacture was found on the label.',
        evidence_excerpt: 'Net Qty: 500 g MRP Rs. 149.00',
        violation: 10,
      }),
      findingBody({
        id: 4,
        rule_code: 'LMPC-IMPORTER-001',
        clause: '6(1)(aa)',
        title: 'Importer details for imported packages',
        field_key: 'importer',
        status: 'inconclusive',
        extracted_raw_value: '',
        extracted_normalized_value: null,
        extracted_confidence: null,
        message: 'Whether this package is imported has not been stated, so this requirement could not be decided.',
        evidence_excerpt: '',
        applicability_note: 'Applies only to imported packages; the fact was not declared.',
      }),
      findingBody({
        id: 5,
        rule_code: 'LMPC-BIDI-001',
        clause: '26(c)',
        title: 'Bidi packages',
        field_key: '',
        status: 'not_applicable',
        extracted_raw_value: '',
        extracted_normalized_value: null,
        extracted_confidence: null,
        message: 'The package was declared not to contain bidi, so this rule does not govern it.',
        evidence_excerpt: '',
      }),
    ],
    extraction: extractionRunBody(),
    image: imageBody(),
    ...overrides,
  };
}

export function selectedImage(overrides: Partial<SelectedImage> = {}): SelectedImage {
  return {
    uri: 'file:///data/user/0/in.legalmetrology.labelcheck/cache/ImagePicker/label.jpg',
    name: 'label.jpg',
    type: 'image/jpeg',
    sizeBytes: 234567,
    width: 1600,
    height: 1200,
    ...overrides,
  };
}

/** A minimal `Response` for a stubbed `fetch`. */
export function jsonResponse(body: unknown, { status = 200 }: { status?: number } = {}): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

export function errorEnvelope(code: string, message: string, details: unknown = null) {
  return { error: { code, message, details } };
}

/** A camera permission response, as expo-image-picker shapes it. */
export function cameraPermission(granted: boolean, canAskAgain = true): ImagePicker.PermissionResponse {
  return {
    status: granted ? ImagePicker.PermissionStatus.GRANTED : ImagePicker.PermissionStatus.DENIED,
    granted,
    canAskAgain,
    expires: 'never',
  };
}

/** A photo-library permission response, as expo-image-picker shapes it. */
export function libraryPermission(granted: boolean, canAskAgain = true): ImagePicker.MediaLibraryPermissionResponse {
  return { ...cameraPermission(granted, canAskAgain), accessPrivileges: granted ? 'all' : 'none' };
}

/** The body of `GET /api/v1/health/` as the deployed backend returns it. */
export function healthBody(overrides: Record<string, unknown> = {}) {
  return {
    status: 'ok',
    api_version: 'v1',
    dependencies: { database: 'ok', extraction_engine: 'ok' },
    extraction_engine: { name: 'tesseract', version: '0.3.0', is_placeholder: false, available: true, detail: '' },
    compliance_rules: { active_total: 11, verified: 11, unverified: 0, applicability_conditions: 39 },
    ...overrides,
  };
}

/**
 * A `fetch` stub that answers `health/` from `health` and everything else from
 * a queue, in order. The home screen checks the server on mount, so a screen
 * test that also uploads needs the two kept apart.
 */
export function routedFetch({
  health = jsonResponse(healthBody()),
  queue = [],
}: {
  health?: Response | Error;
  queue?: (Response | Error)[];
} = {}) {
  const pending = [...queue];
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const stub = jest.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const answer = /\/health\/$/.test(url) ? health : pending.shift();
    if (answer === undefined) {
      throw new Error(`routedFetch: no response queued for ${url}`);
    }
    if (answer instanceof Error) {
      throw answer;
    }
    return answer;
  });
  return Object.assign(stub, { calls });
}
