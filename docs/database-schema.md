# Database Schema & Data Contract

**Project:** Legal Metrology Compliance Checker
**Database:** PostgreSQL
**Backend ORM:** Django ORM
**Document owner:** Samarth — Database / Schema / Data Contract
**Status:** Initial database contract
**Last reviewed:** 2026-08-26

---

# 1. Purpose

This document defines the database schema and persistence data contract for the
Legal Metrology Compliance Checker.

It documents the persistence design implemented by the Django models and
migrations. It does not take ownership of Django models, migrations, APIs,
OCR, extraction, compliance-engine implementation, or legal-rule authoring.

The database stores:

- product identity and categorisation
- uploaded product images
- extraction runs
- extracted label fields
- compliance rules
- compliance checks
- compliance violations
- compliance evidence
- audit/provenance information

The persistence design must preserve enough provenance to understand:

1. which product was evaluated;
2. which image supplied the source evidence;
3. which extraction run produced an observed value;
4. which rule was evaluated;
5. what result was produced; and
6. what evidence supports a finding.

---

# 2. Ownership Boundaries

| Area | Owner | Database responsibility |
|---|---|---|
| PostgreSQL configuration | Samarth / Piyush | Configuration contract |
| Database schema documentation | Samarth | Primary owner |
| Data dictionary | Samarth | Primary owner |
| SQL/schema review | Samarth | Primary owner |
| Django models | Piyush | Implementation owner |
| Django migrations | Piyush | Implementation owner |
| API serializers/endpoints | Piyush | Implementation owner |
| OCR | Raghav | Producer |
| Field extraction | Raghav | Producer |
| Normalisation | Raghav | Producer |
| Compliance-engine implementation | Raghav | Consumer/producer |
| Legal rule authoring | Assigned rule owner | Producer |
| Compliance rule persistence | Piyush | Django implementation |

Samarth may identify schema or data-contract problems in Django models, but
should not take ownership of Piyush's Django implementation.

---

# 3. PostgreSQL Contract

## 3.1 Database engine

The application uses PostgreSQL through Django's PostgreSQL backend.

Expected environment configuration:

| Setting | Purpose |
|---|---|
| `DATABASE_NAME` | PostgreSQL database name |
| `DATABASE_USER` | PostgreSQL user |
| `DATABASE_PASSWORD` | PostgreSQL password |
| `DATABASE_HOST` | PostgreSQL host |
| `DATABASE_PORT` | PostgreSQL port |
| `DATABASE_CONN_MAX_AGE` | Django connection reuse |

Credentials must never be committed to the repository.

## 3.2 PostgreSQL version

Project documentation specifies PostgreSQL 14 or newer.

## 3.3 Time

Timestamp fields use Django `DateTimeField` and therefore follow the project's
timezone configuration.

Common lifecycle timestamps are:

- `created_at`
- `updated_at`

Where applicable, processing entities also contain:

- `started_at`
- `completed_at`
- `processing_ms`

---

# 4. Primary Keys + Nullability

## 4.1 Primary-key convention

The schema deliberately uses UUID and BigAutoField primary keys.

| Model | Primary key | Type |
|---|---|---|
| `Product` | `id` | UUID |
| `ProductImage` | `id` | UUID |
| `ExtractionRun` | `id` | UUID |
| `ComplianceCheck` | `id` | UUID |
| `ProductCategory` | `id` | BigAutoField |
| `ComplianceRule` | `id` | BigAutoField |
| `ExtractedLabelField` | `id` | BigAutoField |
| `ComplianceViolation` | `id` | BigAutoField |
| `ComplianceEvidence` | `id` | BigAutoField |

UUIDs are used for the main workflow/domain objects:

- Product
- ProductImage
- ExtractionRun
- ComplianceCheck

BigAutoField is used for catalogue and child records whose database identifier
is primarily an internal relational identifier.

For `ProductCategory`, the stable business identifier is `code`.

For `ComplianceRule`, the stable business identifier is `code`.

The database primary key and business identifier are therefore separate
concepts for those models.

## 4.2 Nullability convention

Database nullability represents whether the absence of a value is a valid
persisted state.

| Field | Database nullable | Meaning of `NULL` |
|---|---:|---|
| `ProductCategory.parent` | Yes | Category has no parent |
| `Product.category` | Yes | Product category has not yet been identified |
| `Product.created_by` | Yes | Creating user is no longer available or was not associated |
| `ProductImage.product` | Yes | Image has not yet been linked to a product |
| `ProductImage.uploaded_by` | Yes | Uploading user is no longer available or was not associated |
| `ExtractionRun.started_at` | Yes | Extraction has not started or time was not recorded |
| `ExtractionRun.completed_at` | Yes | Extraction has not completed or time was not recorded |
| `ExtractionRun.processing_ms` | Yes | Processing duration is unavailable |
| `ExtractedLabelField.normalized_value` | Yes | No structured normalized representation is available |
| `ExtractedLabelField.confidence` | Yes | Producer did not provide confidence |
| `ExtractedLabelField.bounding_box` | Yes | Source-image location is unavailable |
| `ComplianceRule.effective_from` | Yes | No explicit start date |
| `ComplianceRule.effective_to` | Yes | No explicit end date |
| `ComplianceCheck.product` | Yes | Check can exist before a product is linked |
| `ComplianceCheck.requested_by` | Yes | Requesting user is no longer available or was not associated |
| `ComplianceCheck.started_at` | Yes | Evaluation has not started or time was not recorded |
| `ComplianceCheck.completed_at` | Yes | Evaluation has not completed or time was not recorded |
| `ComplianceCheck.processing_ms` | Yes | Evaluation duration is unavailable |
| `ComplianceEvidence.extracted_field` | Yes | Evidence is not tied to one extracted field |
| `ComplianceEvidence.image` | Yes | Evidence is not tied to an available image |

Important distinction: Django `blank=True` does **not** make a database column
nullable. A field without `null=True` remains database `NOT NULL`, even when
the application accepts an empty value.

Examples:

- `Product.name` is `NOT NULL` and may be an empty string.
- `Product.brand` is `NOT NULL` and may be an empty string.
- `Product.barcode` is `NOT NULL` and may be an empty string.
- `Product.notes` is `NOT NULL` and may be an empty string.
- `ExtractionRun.error_code` is `NOT NULL` and may be an empty string.
- `ExtractionRun.error_message` is `NOT NULL` and may be an empty string.
- `ExtractionRun.raw_output` is `NOT NULL` and defaults to `{}`.
- `ExtractionRun.recognised_text` is `NOT NULL` and may be an empty string.
- `ComplianceRule.legal_reference` is `NOT NULL` and may be an empty string.
- `ComplianceRule.source_note` is `NOT NULL` and may be an empty string.
- `ComplianceRule.parameters` is `NOT NULL` and defaults to `{}`.
- `ComplianceCheck.summary` is `NOT NULL` and may be an empty string.
- `ComplianceEvidence.excerpt` is `NOT NULL` and may be an empty string.
- `ComplianceEvidence.note` is `NOT NULL` and may be an empty string.

Other semantic rules:

- `Product.category = NULL` means applicability cannot yet be determined from
  category information.
- `ExtractionRun.status = EMPTY` means the extraction completed without usable
  recognition; it is not a compliance verdict.
- `ExtractedLabelField.confidence = NULL` means confidence was not supplied.
  It must not be interpreted as zero confidence.
- `ExtractedLabelField.normalized_value = NULL` means no structured
  normalization is available.
- `ComplianceCheck.result = REVIEW_REQUIRED` means the system has not
  established a definitive compliant result.
- An absence of applicable rules must not automatically be interpreted as proof
  of compliance.

## 4.3 Delete behaviour

Foreign-key deletion policies are part of the data-lifecycle contract.

| Relationship | Delete behaviour |
|---|---|
| `Product.category` → `ProductCategory` | `PROTECT` |
| `Product.created_by` → `User` | `SET_NULL` |
| `ProductCategory.parent` → `ProductCategory` | `PROTECT` |
| `ProductImage.product` → `Product` | `CASCADE` |
| `ProductImage.uploaded_by` → `User` | `SET_NULL` |
| `ExtractionRun.image` → `ProductImage` | `CASCADE` |
| `ExtractedLabelField.run` → `ExtractionRun` | `CASCADE` |
| `ComplianceRule.applies_to_categories` → `ProductCategory` | `CASCADE` |
| `ComplianceCheck.extraction_run` → `ExtractionRun` | `CASCADE` |
| `ComplianceCheck.product` → `Product` | `CASCADE` |
| `ComplianceCheck.requested_by` → `User` | `SET_NULL` |
| `ComplianceViolation.compliance_check` → `ComplianceCheck` | `CASCADE` |
| `ComplianceViolation.rule` → `ComplianceRule` | `PROTECT` |
| `ComplianceEvidence.violation` → `ComplianceViolation` | `CASCADE` |
| `ComplianceEvidence.extracted_field` → `ExtractedLabelField` | `SET_NULL` |
| `ComplianceEvidence.image` → `ProductImage` | `SET_NULL` |

The Django models and migrations remain the implementation authority for
actual database behaviour.

---

# 5. Entity Relationship Overview

The main persistence flow is:

```text
ProductCategory
      │
      └──────────────► Product
                         │
                         ▼
                    ProductImage
                         │
                         ▼
                    ExtractionRun
                         │
                         ▼
               ExtractedLabelField
                         │
                         ▼
                  ComplianceCheck
                     │        │
                     │        └──────────────► ComplianceRule
                     │
                     ▼
              ComplianceViolation
                     │
                     ▼
              ComplianceEvidence
```

Compliance rules also have a many-to-many relationship with product
categories:

```text
ProductCategory ◄────────► ComplianceRule
```

A compliance check references both a product and an extraction run.

---

# 6. Product Domain

## 6.1 ProductCategory

**Purpose:** Represents a commodity/product category used for classification
and rule applicability.

| Field | Django type | DB nullable | Purpose |
|---|---|---:|---|
| `id` | BigAutoField | No | Primary key |
| `created_at` | DateTimeField | No | Creation timestamp |
| `updated_at` | DateTimeField | No | Last-update timestamp |
| `code` | SlugField | No | Stable category identifier |
| `name` | CharField | No | Human-readable category name |
| `description` | TextField | No | Category description; may be empty |
| `is_active` | BooleanField | No | Whether category is active |
| `parent` | ForeignKey → ProductCategory | Yes | Optional parent category |

### Constraints and indexes

- `code` is unique.
- Ordering: `code`.
- `parent` uses `PROTECT`.
- `parent` uses `related_name="children"`.

### Contract

`code` is a stable identifier referenced by rule definition files.

Categories may form a hierarchy.

---

## 6.2 Product

**Purpose:** Represents the product identity being evaluated.

| Field | Django type | DB nullable | Purpose |
|---|---|---:|---|
| `created_at` | DateTimeField | No | Creation timestamp |
| `updated_at` | DateTimeField | No | Last-update timestamp |
| `id` | UUIDField | No | Primary key |
| `name` | CharField | No | Working product name; may be empty |
| `brand` | CharField | No | Brand; may be empty |
| `barcode` | CharField | No | EAN/UPC when known; may be empty |
| `notes` | TextField | No | Additional notes; may be empty |
| `created_by` | ForeignKey → User | Yes | Creating user |
| `category` | ForeignKey → ProductCategory | Yes | Product category |

### Constraints and indexes

- UUID primary key.
- Ordering: `-created_at`.
- Index: `product_created_idx` on `-created_at`.
- `created_by` uses `SET_NULL`.
- `category` uses `PROTECT`.

### Contract

Product identity is separate from extracted label observations.

A product may exist without a completed extraction.

A product category may remain `NULL` until classification is available.

---

# 7. Image Domain

## 7.1 ProductImage

**Purpose:** Stores an uploaded image used as visual evidence for extraction
and compliance evaluation.

| Field | Django type | DB nullable | Purpose |
|---|---|---:|---|
| `created_at` | DateTimeField | No | Creation timestamp |
| `updated_at` | DateTimeField | No | Last-update timestamp |
| `id` | UUIDField | No | Primary key |
| `image` | FileField | No | Stored image |
| `original_filename` | CharField | No | Sanitised client filename |
| `content_type` | CharField | No | MIME/content type |
| `image_format` | CharField | No | Canonical decoded format |
| `size_bytes` | PositiveBigIntegerField | No | Image size |
| `width` | PositiveIntegerField | No | Image width |
| `height` | PositiveIntegerField | No | Image height |
| `checksum_sha256` | CharField | No | SHA-256 content checksum |
| `view_type` | CharField | No | Image/view classification |
| `status` | CharField | No | Image processing state |
| `product` | ForeignKey → Product | Yes | Associated product |
| `uploaded_by` | ForeignKey → User | Yes | Uploading user |

### Choices

`view_type`:

- `unspecified`
- `front`
- `back`
- `principal_display`
- `label`
- `other`

`status`:

- `uploaded`
- `processing`
- `processed`
- `failed`

### Constraints and indexes

- UUID primary key.
- Ordering: `-created_at`.
- Index: `image_product_view_idx` on `product, view_type`.
- `product` uses `CASCADE`.
- `uploaded_by` uses `SET_NULL`.

### Contract

The product relationship is nullable because an image can exist before product
identification is complete.

`checksum_sha256` ties processing and evidence to the exact uploaded bytes.

---

# 8. Extraction Domain

## 8.1 ExtractionRun

**Purpose:** Represents one attempt to process a `ProductImage` through an
extraction pipeline.

| Field | Django type | DB nullable | Purpose |
|---|---|---:|---|
| `created_at` | DateTimeField | No | Creation timestamp |
| `updated_at` | DateTimeField | No | Last-update timestamp |
| `id` | UUIDField | No | Primary key |
| `engine_name` | CharField | No | Extraction engine/pipeline name |
| `engine_version` | CharField | No | Engine version |
| `is_placeholder` | BooleanField | No | Whether placeholder engine was used |
| `status` | CharField | No | Extraction lifecycle |
| `started_at` | DateTimeField | Yes | Processing start |
| `completed_at` | DateTimeField | Yes | Processing completion |
| `processing_ms` | PositiveIntegerField | Yes | Processing duration |
| `error_code` | CharField | No | Machine-readable error; may be empty |
| `error_message` | TextField | No | Human-readable error; may be empty |
| `raw_output` | JSONField | No | Raw engine output; defaults to `{}` |
| `recognised_text` | TextField | No | Recognised text; may be empty |
| `image` | ForeignKey → ProductImage | No | Source image |

### Status choices

- `pending`
- `running`
- `completed`
- `empty`
- `failed`

### Constraints and indexes

- UUID primary key.
- Ordering: `-created_at`.
- Index: `run_image_recent_idx` on `image, -created_at`.
- `image` uses `CASCADE`.

### Contract

`raw_output` preserves engine diagnostics.

`recognised_text` stores the joined recognised text.

`EMPTY` represents an extraction outcome in which usable recognition was not
obtained.

`FAILED` represents a processing failure.

---

## 8.2 ExtractedLabelField

**Purpose:** Stores an individual declaration/field observed during an
extraction run.

| Field | Django type | DB nullable | Purpose |
|---|---|---:|---|
| `id` | BigAutoField | No | Primary key |
| `created_at` | DateTimeField | No | Creation timestamp |
| `updated_at` | DateTimeField | No | Last-update timestamp |
| `field_key` | CharField | No | Extraction field vocabulary identifier |
| `raw_value` | TextField | No | Original extracted value |
| `normalized_value` | JSONField | Yes | Structured normalized interpretation |
| `confidence` | FloatField | Yes | Engine confidence in `[0,1]` |
| `bounding_box` | JSONField | Yes | Source-image coordinates |
| `run` | ForeignKey → ExtractionRun | No | Producing extraction run |

### Constraints and indexes

- BigAutoField primary key.
- Ordering: `field_key`.
- Index: `field_run_key_idx` on `run, field_key`.
- `run` uses `CASCADE`.

### Contract

`field_key` is a service-layer vocabulary identifier. It is intentionally not
implemented as a database enum.

`raw_value` preserves what was observed.

`normalized_value` is an interpretation and must not replace the raw value.

`confidence = NULL` means the producer did not provide confidence.

---

# 9. Compliance Rule Domain

## 9.1 ComplianceRule

**Purpose:** Stores a machine-readable compliance requirement derived from
reviewed legal material.

| Field | Django type | DB nullable | Purpose |
|---|---|---:|---|
| `id` | BigAutoField | No | Primary key |
| `created_at` | DateTimeField | No | Creation timestamp |
| `updated_at` | DateTimeField | No | Last-update timestamp |
| `code` | SlugField | No | Stable rule identifier |
| `title` | CharField | No | Rule title |
| `requirement` | TextField | No | Plain-language requirement |
| `legal_reference` | CharField | No | Legal source reference; may be empty |
| `source_status` | CharField | No | Verification status |
| `source_note` | TextField | No | Verification/source notes; may be empty |
| `severity` | CharField | No | Finding severity |
| `check_type` | CharField | No | Registered validator identifier |
| `parameters` | JSONField | No | Rule-specific configuration; defaults to `{}` |
| `effective_from` | DateField | Yes | First applicable date |
| `effective_to` | DateField | Yes | Last applicable date |
| `is_active` | BooleanField | No | Whether rule is active |
| `applies_to_categories` | ManyToMany → ProductCategory | N/A | Applicable categories |

### Choices

`source_status`:

- `verified`
- `unverified`

`severity`:

- `info`
- `minor`
- `major`
- `critical`

### Constraints and indexes

- BigAutoField primary key.
- `code` is unique.
- Index: `rule_active_source_idx` on `is_active, source_status`.
- Ordering: `code`.
- Many-to-many relationship uses `related_name="rules"`.
- The many-to-many field is optional at the database level.
- `applies_to_categories` uses the normal many-to-many join table.
- Deleting a category cascades the applicability relationship.

### Contract

`code` is the stable rule identifier referenced by results and rule definition
files.

`parameters` is structured rule configuration and is not nullable.

Historical findings store rule-code and legal-reference snapshots so that
future changes to the live rule do not silently rewrite historical findings.

---

# 10. Compliance Result Domain

## 10.1 ComplianceCheck

**Purpose:** Represents one compliance evaluation using a specific extraction
run.

| Field | Django type | DB nullable | Purpose |
|---|---|---:|---|
| `created_at` | DateTimeField | No | Creation timestamp |
| `updated_at` | DateTimeField | No | Last-update timestamp |
| `id` | UUIDField | No | Primary key |
| `status` | CharField | No | Evaluation lifecycle |
| `result` | CharField | No | Compliance verdict |
| `engine_version` | CharField | No | Compliance engine version |
| `rules_evaluated` | PositiveIntegerField | No | Applicable rules evaluated |
| `rules_passed` | PositiveIntegerField | No | Rules passed |
| `rules_failed` | PositiveIntegerField | No | Rules failed |
| `rules_inconclusive` | PositiveIntegerField | No | Rules not conclusively decided |
| `summary` | TextField | No | Result summary; may be empty |
| `started_at` | DateTimeField | Yes | Evaluation start |
| `completed_at` | DateTimeField | Yes | Evaluation completion |
| `processing_ms` | PositiveIntegerField | Yes | Evaluation duration |
| `extraction_run` | ForeignKey → ExtractionRun | No | Evidence-producing extraction |
| `product` | ForeignKey → Product | Yes | Evaluated product |
| `requested_by` | ForeignKey → User | Yes | Requesting user |

### Status choices

- `pending`
- `running`
- `completed`
- `failed`

### Result choices

- `compliant`
- `partially_compliant`
- `non_compliant`
- `review_required`

### Constraints and indexes

- UUID primary key.
- Ordering: `-created_at`.
- Index: `check_product_idx` on `product, -created_at`.
- Index: `check_result_idx` on `result`.
- `extraction_run` uses `CASCADE`.
- `product` uses `CASCADE`.
- `requested_by` uses `SET_NULL`.

### Contract

`REVIEW_REQUIRED` is not equivalent to compliant.

A compliance check remains associated with the extraction run from which the
evaluated observations originated.

The product relationship is nullable in the current implementation and must
therefore be treated as a legitimate pre-linking state.

---

## 10.2 ComplianceViolation

**Purpose:** Represents a rule-level finding produced by a compliance check.

| Field | Django type | DB nullable | Purpose |
|---|---|---:|---|
| `id` | BigAutoField | No | Primary key |
| `created_at` | DateTimeField | No | Creation timestamp |
| `updated_at` | DateTimeField | No | Last-update timestamp |
| `severity` | CharField | No | Severity snapshot |
| `rule_code` | CharField | No | Rule-code snapshot |
| `legal_reference` | CharField | No | Legal-reference snapshot; may be empty |
| `field_key` | CharField | No | Related extraction field key; may be empty |
| `message` | TextField | No | Human-readable finding |
| `compliance_check` | ForeignKey → ComplianceCheck | No | Parent evaluation |
| `rule` | ForeignKey → ComplianceRule | No | Rule that produced finding |

### Constraints and indexes

- BigAutoField primary key.
- Ordering: `rule_code`.
- Index: `violation_check_sev_idx` on `compliance_check, severity`.
- `compliance_check` uses `CASCADE`.
- `rule` uses `PROTECT`.

### Contract

`rule_code` and `legal_reference` are snapshots.

They preserve historical interpretation even if the current `ComplianceRule`
record is subsequently amended.

`field_key` is database `NOT NULL`; Django `blank=True` means it may contain an
empty string rather than SQL `NULL`.

---

## 10.3 ComplianceEvidence

**Purpose:** Links a finding to source evidence.

| Field | Django type | DB nullable | Purpose |
|---|---|---:|---|
| `id` | BigAutoField | No | Primary key |
| `created_at` | DateTimeField | No | Creation timestamp |
| `updated_at` | DateTimeField | No | Last-update timestamp |
| `excerpt` | TextField | No | Evidence text; may be empty |
| `bounding_box` | JSONField | Yes | Source-image location |
| `note` | TextField | No | Evidence explanation; may be empty |
| `extracted_field` | ForeignKey → ExtractedLabelField | Yes | Supporting extracted value |
| `image` | ForeignKey → ProductImage | Yes | Supporting image |
| `violation` | ForeignKey → ComplianceViolation | No | Parent finding |

### Constraints

- BigAutoField primary key.
- Ordering: `id`.
- `verbose_name_plural = "compliance evidence"`.
- `violation` uses `CASCADE`.
- `extracted_field` uses `SET_NULL`.
- `image` uses `SET_NULL`.

### Contract

Evidence remains traceable to an image and/or extracted field when those
references are available.

`excerpt` and `note` are database `NOT NULL`; an empty string is distinct from
SQL `NULL`.

---

# 11. Relationship Contract

| Parent | Child / Related | Relationship | Meaning |
|---|---|---|---|
| ProductCategory | Product | 1:N | Products may belong to a category |
| ProductCategory | ProductCategory | 1:N | Categories may form a hierarchy |
| Product | ProductImage | 1:N | Product may have multiple images |
| ProductImage | ExtractionRun | 1:N | Image may be processed multiple times |
| ExtractionRun | ExtractedLabelField | 1:N | Run produces observed fields |
| Product | ComplianceCheck | 1:N | Product may be evaluated multiple times |
| ExtractionRun | ComplianceCheck | 1:N | Extraction may support multiple evaluations |
| ComplianceRule | ProductCategory | N:M | Rule applicability |
| ComplianceCheck | ComplianceViolation | 1:N | Evaluation produces findings |
| ComplianceViolation | ComplianceEvidence | 1:N | Finding may have evidence |
| ExtractedLabelField | ComplianceEvidence | 1:N | Field may support evidence |
| ProductImage | ComplianceEvidence | 1:N | Image may support evidence |

---

# 12. Data Provenance Contract

The principal provenance chain is:

```text
SOURCE IMAGE
     │
     ▼
EXTRACTION RUN
     │
     ▼
EXTRACTED FIELD
     │
     ▼
COMPLIANCE CHECK
     │
     ▼
VIOLATION
     │
     ▼
EVIDENCE
```

The database must not reduce this chain to only a final compliance verdict.

A historical result should remain explainable in terms of the product,
extraction run, rule, finding, and available evidence.

---

# 13. JSON Usage Contract

JSON is used where data is naturally semi-structured or owned by another
contract.

Confirmed JSON-backed fields are:

| Model | Field | Purpose |
|---|---|---|
| `ExtractionRun` | `raw_output` | Raw extraction-engine output |
| `ExtractedLabelField` | `normalized_value` | Structured interpretation of a field |
| `ExtractedLabelField` | `bounding_box` | Image coordinates |
| `ComplianceRule` | `parameters` | Rule-specific configuration |
| `ComplianceEvidence` | `bounding_box` | Evidence image coordinates |

JSON must not replace relational entities that require referential integrity,
relational querying, filtering, or historical relationships.

---

# 14. Nullability Semantics

`NULL` does not have one universal meaning.

| Field | NULL meaning |
|---|---|
| `ProductCategory.parent` | No parent category |
| `Product.category` | Category not currently assigned |
| `Product.created_by` | Creating user unavailable |
| `ProductImage.product` | Product not yet linked |
| `ProductImage.uploaded_by` | Uploading user unavailable |
| `ExtractionRun.started_at` | Start time unavailable |
| `ExtractionRun.completed_at` | Completion time unavailable |
| `ExtractionRun.processing_ms` | Processing duration unavailable |
| `ExtractedLabelField.normalized_value` | Normalized representation unavailable |
| `ExtractedLabelField.confidence` | Producer did not provide confidence |
| `ExtractedLabelField.bounding_box` | Location unavailable |
| `ComplianceRule.effective_from` | No explicit start date |
| `ComplianceRule.effective_to` | No explicit end date |
| `ComplianceCheck.product` | Product not linked |
| `ComplianceCheck.requested_by` | Requesting user unavailable |
| `ComplianceCheck.started_at` | Start time unavailable |
| `ComplianceCheck.completed_at` | Completion time unavailable |
| `ComplianceCheck.processing_ms` | Evaluation duration unavailable |
| `ComplianceEvidence.extracted_field` | No direct extracted-field relationship |
| `ComplianceEvidence.image` | No available source-image relationship |

Application code must not interpret all NULL values as failures.

Also, an empty string is not the same as SQL `NULL`. Several Django fields use
`blank=True` without `null=True`, so they remain database `NOT NULL`.

---

# 15. Historical Data Contract

Compliance results are historical records.

The persistence layer preserves the context required to interpret a past
evaluation, including:

- product identity
- extraction run
- extracted observations
- rule identity
- rule-code snapshot
- legal-reference snapshot
- finding
- evidence

Changing the current rule definition must not silently rewrite the meaning of
an existing historical violation.

The rule foreign key is protected, while the violation additionally stores
snapshots of rule identity and legal reference.

---

# 16. Deletion Policy

Foreign-key deletion behaviour is part of the database contract.

## Product domain

- Product → ProductCategory: `PROTECT`
- Product → User (`created_by`): `SET_NULL`
- ProductImage → Product: `CASCADE`
- ProductImage → User (`uploaded_by`): `SET_NULL`

## Extraction domain

- ExtractionRun → ProductImage: `CASCADE`
- ExtractedLabelField → ExtractionRun: `CASCADE`

## Rule domain

- ComplianceRule ↔ ProductCategory applicability: category deletion removes the
  applicability relationship.
- ComplianceViolation → ComplianceRule: `PROTECT`

## Compliance domain

- ComplianceCheck → ExtractionRun: `CASCADE`
- ComplianceCheck → Product: `CASCADE`
- ComplianceCheck → User (`requested_by`): `SET_NULL`
- ComplianceViolation → ComplianceCheck: `CASCADE`
- ComplianceEvidence → ComplianceViolation: `CASCADE`
- ComplianceEvidence → ExtractedLabelField: `SET_NULL`
- ComplianceEvidence → ProductImage: `SET_NULL`

No deletion policy should be changed merely for convenience where it would
destroy required relational or historical meaning.

---

# 17. Index and Constraint Inventory

## Primary keys

| Model | Primary key |
|---|---|
| ProductCategory | `id` BigAutoField |
| Product | `id` UUID |
| ProductImage | `id` UUID |
| ExtractionRun | `id` UUID |
| ExtractedLabelField | `id` BigAutoField |
| ComplianceRule | `id` BigAutoField |
| ComplianceCheck | `id` UUID |
| ComplianceViolation | `id` BigAutoField |
| ComplianceEvidence | `id` BigAutoField |

## Unique constraints

| Model | Constraint |
|---|---|
| ProductCategory | `code` unique |
| ComplianceRule | `code` unique |

No other model-level `unique=True` constraints are present in the supplied
initial migrations.

## Explicit indexes

| Model | Index | Fields |
|---|---|---|
| Product | `product_created_idx` | `-created_at` |
| ProductImage | `image_product_view_idx` | `product, view_type` |
| ExtractionRun | `run_image_recent_idx` | `image, -created_at` |
| ExtractedLabelField | `field_run_key_idx` | `run, field_key` |
| ComplianceRule | `rule_active_source_idx` | `is_active, source_status` |
| ComplianceCheck | `check_product_idx` | `product, -created_at` |
| ComplianceCheck | `check_result_idx` | `result` |
| ComplianceViolation | `violation_check_sev_idx` | `compliance_check, severity` |

Additional single-column indexes are created automatically by Django for
fields with `db_index=True`, including:

- `Product.barcode`
- `ProductImage.checksum_sha256`
- `ProductImage.status`
- `ExtractionRun.status`
- `ExtractedLabelField.field_key`
- `ComplianceRule.source_status`
- `ComplianceRule.check_type`
- `ComplianceRule.is_active`
- `ComplianceCheck.status`
- `ComplianceCheck.result`
- `ComplianceViolation.rule_code`

The exact database-generated index names are implementation details unless
explicitly named in the migration.

## Check constraints

No Django `CheckConstraint` is defined in the supplied initial migrations.

Some semantic validation is documented in model help text or is expected to be
handled by the application/service layer.

---

# 18. Producer / Consumer Data Contract

## Product data

**Producer:** Product/API layer
**Stored by:** Django/PostgreSQL
**Consumers:** Extraction, compliance, API/UI

## Image data

**Producer:** Image upload layer
**Stored by:** Django/PostgreSQL
**Consumers:** Extraction, evidence

## Extracted fields

**Producer:** Extraction/ML layer
**Stored by:** Django/PostgreSQL
**Consumers:** Compliance, API/UI

## Compliance rules

**Producer:** Rule-definition/rule-loading workflow
**Stored by:** Django/PostgreSQL
**Consumers:** Compliance engine

## Compliance results

**Producer:** Compliance engine
**Stored by:** Django/PostgreSQL
**Consumers:** API/UI/reviewer

## Compliance evidence

**Producer:** Compliance engine
**Stored by:** Django/PostgreSQL
**Consumers:** API/UI/reviewer/audit

---

# 19. Current Database Contract Status

The initial migrations provide the principal domain entities:

- product categories
- products
- product images
- extraction runs
- extracted label fields
- compliance rules
- compliance checks
- compliance violations
- compliance evidence

The current documentation contract now explicitly records:

- primary-key types
- nullability
- blank-vs-null semantics
- defaults
- foreign-key relationships
- deletion behaviour
- indexes
- unique constraints
- JSON fields
- result/status states
- provenance
- rule snapshots
- producer/consumer ownership

The Django models and migrations remain the implementation authority.

This document must not invent schema elements that are not represented by the
implementation.

---

# 20. Ownership Rules for Future Changes

Samarth should:

- maintain this database contract;
- identify schema/data-contract gaps;
- document PostgreSQL assumptions;
- review relational integrity;
- document indexes and constraints;
- document data lifecycle and provenance;
- propose schema changes when justified.

Piyush should:

- modify Django models;
- create Django migrations;
- implement ORM constraints;
- implement serializers;
- implement API changes.

Raghav should:

- define extraction field semantics;
- produce extracted data;
- define extraction/compliance integration behaviour;
- implement OCR/extraction/compliance logic.

Samarth must not independently modify Piyush's Django models or migrations
unless ownership is explicitly reassigned.

---

# 21. Change Control

A proposed database schema change should follow:

1. Identify the data-contract requirement.
2. Document the problem.
3. Update this database contract.
4. Review impact on existing relationships and data.
5. Hand implementation to Piyush.
6. Piyush creates the Django model/migration change.
7. Verify the resulting PostgreSQL schema.
8. Update this document.

Existing migrations should not be edited merely to correct documentation.

New schema changes should use new migrations.

---

# 22. Verification Checklist

Before declaring the database contract complete, verify:

- [x] Every model in the supplied initial migrations is represented.
- [x] Every migration-created table is represented.
- [x] Primary-key types are documented.
- [x] Foreign keys are documented.
- [x] Nullability is documented.
- [x] Django `blank=True` versus database `NULL` semantics are documented.
- [x] Defaults are documented where present.
- [x] Unique constraints are documented.
- [x] Explicit indexes are documented.
- [x] `db_index=True` fields are identified.
- [x] Foreign-key delete behaviour is documented.
- [x] Product/image/extraction provenance is documented.
- [x] Compliance provenance is documented.
- [x] Rule snapshot behaviour is documented.
- [x] Producer/consumer ownership is documented.
- [x] PostgreSQL configuration is documented without secrets.
- [x] No Django model ownership has been transferred to Samarth.
- [x] No OCR implementation is included.
- [x] No compliance-engine implementation is included.
- [x] No legal-rule authoring is included.

---

# 23. Source of Truth for This Document

This document was reconciled against the supplied initial Django migrations:

- `apps/catalog/migrations/0001_initial.py`
- `apps/images/migrations/0001_initial.py`
- `apps/extraction/migrations/0001_initial.py`
- `apps/rules/migrations/0001_initial.py`
- `apps/compliance/migrations/0001_initial.py`

Where this document and the Django migrations disagree, the migrations are the
implementation authority and this document must be corrected rather than the
migration being edited for documentation purposes.
