/**
 * The API contract, as the backend sends it.
 *
 * Everything in the first half of this file is `snake_case` and matches the
 * serializers in `backend/apps/compliance/api/serializers.py`,
 * `backend/apps/extraction/api/serializers.py` and
 * `backend/apps/images/api/serializers.py` field for field. The `src/api/`
 * modules map these onto the camelCase shapes in the second half at the
 * boundary, so a change to the wire format is contained in one place.
 *
 * Nothing here is invented. If the API does not expose something the app
 * needs, that is a documented gap (see docs/mobile.md), not a field added
 * here.
 */

// ---------------------------------------------------------------------------
// Wire shapes
// ---------------------------------------------------------------------------

/** `{ "error": { code, message, details } }` - every failure, every status. */
export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}

export interface BoundingBoxWire {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ExtractedFieldWire {
  field_key: string;
  raw_value: string;
  normalized_value?: Record<string, unknown> | null;
  confidence?: number | null;
  bounding_box?: BoundingBoxWire | null;
}

export interface UnreadDeclarationWire {
  key?: string | null;
  evidence_text?: string;
  confidence?: number | null;
}

/**
 * `labelextract.contracts.ProductClassification.as_dict`, passed through by
 * the backend unchanged. `category` is a `ProductCategory` code or "unknown";
 * `confidence` is the classifier's confidence in that category, or null when
 * it attempted no prediction. It is an observation, never a compliance figure.
 */
export interface ProductClassificationWire {
  category: string;
  subcategory?: string | null;
  confidence?: number | null;
  subcategory_confidence?: number | null;
  evidence?: string[];
  category_scores?: Record<string, number>;
  subcategory_scores?: Record<string, number>;
  classifier_name?: string;
  classifier_version?: string;
}

export interface ExtractionRunWire {
  id: string;
  engine_name: string;
  engine_version: string;
  is_placeholder: boolean;
  status: string;
  produced_usable_output: boolean;
  processing_ms?: number | null;
  recognised_text?: string;
  error_code?: string;
  error_message?: string;
  fields_read?: ExtractedFieldWire[];
  unread_declarations?: UnreadDeclarationWire[];
  /** Absent on a backend that predates the classifier; null when none was made. */
  product_classification?: ProductClassificationWire | null;
}

export interface ProductImageWire {
  id: string;
  original_filename: string;
  image_format: string;
  width: number;
  height: number;
  size_bytes: number;
  view_type: string;
  status: string;
}

/** The body of `POST /api/v1/extraction/`. */
export interface ExtractionResponseWire extends ExtractionRunWire {
  image: ProductImageWire;
}

export interface EvidenceWire {
  excerpt?: string;
  bounding_box?: BoundingBoxWire | null;
  note?: string;
}

export interface ViolationWire {
  id: number;
  rule_code: string;
  legal_reference?: string;
  severity: string;
  field_key?: string;
  message: string;
  evidence?: EvidenceWire[];
}

export interface FindingWire {
  id: number;
  rule_code: string;
  clause?: string;
  title?: string;
  requirement?: string;
  legal_reference?: string;
  legal_source_citation?: string;
  check_type?: string;
  detection_method?: string;
  severity?: string;
  status: string;
  downgraded_from_failed?: boolean;
  applicability_note?: string;
  field_key?: string;
  extracted_raw_value?: string;
  extracted_normalized_value?: Record<string, unknown> | null;
  extracted_confidence?: number | null;
  message?: string;
  evidence_excerpt?: string;
  bounding_box?: BoundingBoxWire | null;
  details?: Record<string, unknown>;
  violation?: number | null;
}

export interface AppliedDeclarationWire {
  code: string;
  name?: string;
  answer: string;
  answer_display?: string;
  source?: string;
  source_display?: string;
  note?: string;
  stated_before_this_check?: boolean | null;
}

/** The compliance result body - `POST /compliance/`, `POST /images/`, `GET /compliance/<uuid>/`. */
export interface ComplianceCheckWire {
  id: string;
  status: string;
  result: string;
  result_display: string;
  summary: string;
  engine_version?: string;
  rules_evaluated?: number;
  rules_passed?: number;
  rules_failed?: number;
  rules_inconclusive?: number;
  rules_not_applicable?: number;
  processing_ms?: number | null;
  completed_at?: string | null;
  product_category_code?: string | null;
  /** Who set the category: submitter | reviewer | classifier. Absent on older backends. */
  product_category_source?: string | null;
  applicability_declarations?: AppliedDeclarationWire[];
  violations?: ViolationWire[];
  findings?: FindingWire[];
  extraction?: ExtractionRunWire | null;
  image?: ProductImageWire | null;
}

/** The JSON body of `POST /api/v1/compliance/`. */
export interface ComplianceEvaluationRequestWire {
  extraction_run_id: string;
  category_code?: string;
  applicability_declarations?: Record<string, 'yes' | 'no' | 'unknown'>;
}

// ---------------------------------------------------------------------------
// Mapped shapes - what the screens render
// ---------------------------------------------------------------------------

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ExtractedField {
  fieldKey: string;
  /** Exactly what the engine read. */
  rawValue: string;
  /** The interpretation, or null when no normaliser ran. */
  normalizedValue: Record<string, unknown> | null;
  /** Null means "not reported", never zero. */
  confidence: number | null;
  boundingBox: BoundingBox | null;
}

export interface UnreadDeclaration {
  fieldKey: string | null;
  evidenceText: string;
  confidence: number | null;
}

export interface ProductClassification {
  /** A `ProductCategory` code, or "unknown" when the classifier declined. */
  category: string;
  subcategory: string | null;
  /** The classifier's confidence in `category`. NOT a compliance figure. */
  confidence: number | null;
  subcategoryConfidence: number | null;
  evidence: string[];
  categoryScores: Record<string, number>;
  classifierName: string;
  classifierVersion: string;
}

export interface ExtractionRun {
  id: string;
  engineName: string;
  engineVersion: string;
  /** True means no recognition happened at all. */
  isPlaceholder: boolean;
  status: string;
  /** Whether the label was read well enough to be judged against. */
  producedUsableOutput: boolean;
  processingMs: number | null;
  recognisedText: string;
  errorCode: string;
  errorMessage: string;
  fieldsRead: ExtractedField[];
  unreadDeclarations: UnreadDeclaration[];
  /**
   * Null means no classification was made - an older backend, a pipeline
   * without a classifier, or a classifier that failed. It is never a category.
   */
  productClassification: ProductClassification | null;
}

export interface ProductImage {
  id: string;
  originalFilename: string;
  imageFormat: string;
  width: number;
  height: number;
  sizeBytes: number;
  viewType: string;
  status: string;
}

export interface Evidence {
  excerpt: string;
  boundingBox: BoundingBox | null;
  note: string;
}

export interface Violation {
  id: number;
  ruleCode: string;
  legalReference: string;
  /** Triage ranking only, no legal weight. */
  severity: string;
  fieldKey: string;
  message: string;
  evidence: Evidence[];
}

/** The four finding statuses the backend defines. Passed through verbatim. */
export type FindingStatus = 'passed' | 'failed' | 'inconclusive' | 'not_applicable';

export interface Finding {
  id: number;
  ruleCode: string;
  clause: string;
  title: string;
  requirement: string;
  legalReference: string;
  legalSourceCitation: string;
  checkType: string;
  detectionMethod: string;
  severity: string;
  /** Verbatim from the backend; a value this build has not seen renders as unknown. */
  status: FindingStatus | string;
  downgradedFromFailed: boolean;
  applicabilityNote: string;
  fieldKey: string;
  extractedRawValue: string;
  extractedNormalizedValue: Record<string, unknown> | null;
  extractedConfidence: number | null;
  message: string;
  evidenceExcerpt: string;
  boundingBox: BoundingBox | null;
  details: Record<string, unknown>;
  violationId: number | null;
}

export interface AppliedDeclaration {
  code: string;
  name: string;
  answer: string;
  answerDisplay: string;
  source: string;
  sourceDisplay: string;
  note: string;
  statedBeforeThisCheck: boolean | null;
}

/** The four verdicts the backend defines. Passed through verbatim. */
export type ComplianceVerdict =
  | 'compliant'
  | 'partially_compliant'
  | 'non_compliant'
  | 'review_required';

export interface ComplianceResult {
  id: string;
  /** Lifecycle of the evaluation: pending | running | completed | failed. */
  status: string;
  /** The verdict, verbatim. Unknown values are rendered as unrecognised. */
  result: ComplianceVerdict | string;
  /** The verdict's human label, from the backend. */
  resultDisplay: string;
  /** The engine's plain-language explanation of the verdict. Always shown. */
  summary: string;
  engineVersion: string;
  rulesEvaluated: number | null;
  rulesPassed: number | null;
  rulesFailed: number | null;
  rulesInconclusive: number | null;
  /** Outside the evaluated sum. Null against a backend that predates the count. */
  rulesNotApplicable: number | null;
  processingMs: number | null;
  completedAt: string | null;
  productCategoryCode: string | null;
  /**
   * `submitter`, `reviewer` or `classifier` - whether a person or, under the
   * backend's accepted policy, the label classifier chose the rule set. Null
   * when there is no category or the backend predates the field.
   */
  productCategorySource: string | null;
  applicabilityDeclarations: AppliedDeclaration[];
  /** False against a backend that sends no `findings` key at all. */
  findingsReported: boolean;
  findings: Finding[];
  violations: Violation[];
  extraction: ExtractionRun | null;
  image: ProductImage | null;
}
