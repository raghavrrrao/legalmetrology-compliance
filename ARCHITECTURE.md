# Architecture

This document explains what each layer owns, how data flows between them, and
which person owns which directory. Read the "Ownership" table before starting a
feature branch.

## Guiding principle

The system must be able to justify every finding. That single requirement
drives most of the structure here: readings are stored separately from products
because a reading is evidence with a source, rules are data because a legal
claim must be reviewable, and results snapshot the rule they came from because
an old finding must keep meaning what it meant.

## Layers

```
┌──────────────────────────────────────────────────────────┐
│  React + Vite  (frontend/)                               │
│  Pages, components, hooks. Talks to exactly one thing:   │
│  services/apiClient.js.                                  │
└───────────────────────────┬──────────────────────────────┘
                            │  HTTP + JSON, CORS-restricted
                            │  /api/v1/...
┌───────────────────────────▼──────────────────────────────┐
│  Django REST API  (backend/apps/*/api/)                  │
│  Serializers, views, routing, validation, error envelope.│
│  Contains NO business logic.                             │
└───────────────────────────┬──────────────────────────────┘
                            │  plain Python calls
┌───────────────────────────▼──────────────────────────────┐
│  Backend services  (backend/apps/*/services/)            │
│  Orchestration and business rules. Where the work is.    │
└─────────┬─────────────────────────────────┬──────────────┘
          │                                 │
┌─────────▼───────────┐          ┌──────────▼───────────────┐
│  PostgreSQL         │          │  labelextract  (ml/)     │
│  Django ORM models  │          │  OCR + field extraction  │
│  Products, images,  │          │  Knows nothing about     │
│  readings, rules,   │          │  Django or the database. │
│  results, evidence  │          └──────────────────────────┘
└─────────────────────┘
```

## The request that matters

The end-to-end flow the whole system exists to serve:

```
  Product image uploaded
        │
        ▼
  apps.images.validators        decode the bytes, measure, checksum
        │                       reject anything that is not a real image
        ▼
  ProductImage row              stored under a generated filename
        │
        ▼
  apps.extraction.services      the ONLY module that imports labelextract
        │
        ▼
  labelextract.ExtractionPipeline
        │  preprocess ──▶ OCR ──▶ field extraction
        ▼
  ExtractionRun + ExtractedLabelField rows
        │                       readings, with confidence and bounding boxes
        ▼
  apps.compliance.services.engine
        │
        ├─▶ which rules apply?   product category + effective date + active
        ├─▶ evaluate each        via apps.rules.checks validators
        ├─▶ verified rules only  can produce a violation
        ▼
  ComplianceCheck + ComplianceViolation + ComplianceEvidence
        │
        ▼
  /api/v1/... JSON response
        │
        ▼
  React UI: result, violations, evidence, and what could NOT be determined
```

## What each layer owns

### Frontend (`frontend/`)

Owns presentation and user interaction. It never contains compliance logic — a
rule must never be implemented in JavaScript, because the browser is not where
a legal determination can be audited.

- `config/env.js` is the only file that reads `import.meta.env`. No component
  hardcodes a backend URL.
- `services/apiClient.js` is the only file that calls `fetch`. It handles the
  error envelope, CSRF and credentials once.
- Every `VITE_` variable is public. Secrets never go here.

### API layer (`backend/apps/*/api/`)

Owns HTTP: routing, serialization, request validation, status codes, the error
envelope. It translates between HTTP and Python and does nothing else.

Complex logic in a view is the main thing to avoid — it cannot be reused by a
management command, cannot be tested without a request, and tends to get copied
rather than shared. Views call services.

Conventions:
- Versioned under `/api/v1/`. A new version is a new namespace, not edits to v1.
- Permissions deny by default (`IsAuthenticated`); public endpoints opt in.
- Every error uses one envelope. See [docs/api.md](docs/api.md).

### Service layer (`backend/apps/*/services/`)

Owns orchestration and business rules. Two services exist today:

- `extraction/services/extraction_service.py` — runs the OCR pipeline and
  persists the result. **The only backend module that imports `labelextract`.**
- `compliance/services/engine.py` — determines applicable rules, evaluates
  them, records violations and evidence, decides the overall result.

### Models (`backend/apps/*/models.py`)

Own persistence and data invariants. Notable decisions:

| Decision | Reason |
|---|---|
| UUID primary keys on `Product`, `ProductImage`, `ExtractionRun`, `ComplianceCheck` | These IDs appear in URLs. Sequential integers would let one user enumerate another's submissions. |
| Label declarations live in `extraction`, not on `Product` | A declaration is a *reading from a photograph*, with a confidence and a source. Copying it onto `Product` would turn evidence into an unsourced assertion. |
| `ExtractionRun` is a FK to image, not a OneToOne | Re-running a better engine must not destroy the readings that existing compliance results cite. |
| `ComplianceCheck` is a FK, not a OneToOne | Rules change; re-evaluating adds a result rather than rewriting history. |
| `ComplianceViolation` snapshots the rule's severity and reference | An amended rule must not silently change what a past finding meant. |
| JSON only for `raw_output`, `parameters`, `normalized_value`, `bounding_box` | Genuinely variable shapes. Everything the engine queries is relational. |

### ML boundary (`ml/`)

Owns OCR and field extraction. The dependency direction is strictly one way:

```
backend  ──imports──▶  labelextract
```

`labelextract` never imports Django, never touches the database, never sees an
HTTP request. Model work is therefore runnable and testable without a database
or a web server — which matters when two people work on OCR and API endpoints
simultaneously.

The backend resolves engines **by name and version** through
`labelextract.registry`. Swapping in a real OCR engine is a settings change
plus a registration inside `ml/`, with no backend code change.

Five distinct responsibilities, kept apart because they fail differently:

1. **Image preprocessing** — deskew, denoise, crop.
2. **OCR** — what characters are there, and where.
3. **Field extraction** — which declaration is this text.
4. **Product classification** — what commodity is this. *(future)*
5. **Compliance reasoning** — is this correct. **Not ML. Lives in the backend.**

OCR and compliance reasoning are not the same thing and must never be merged.
An OCR engine reads characters; it has no opinion about the law.

### Rules (`rules/` + `backend/apps/rules/`)

Owns the compliance requirements, as reviewable data.

- `rules/definitions/*.json` — the rules, in Git, reviewed via pull request.
- `apps/rules/loader.py` — strict validation and idempotent import.
- `apps/rules/checks/` — validators, which answer *mechanical* questions.
- `apps/rules/models.py` — `ComplianceRule`, including `source_status`.

The split that makes this work: a **validator** asks a factual question ("was
this declaration found?"). A **rule row** supplies the legal claim ("this
declaration is required for this commodity"). Machinery and legal content are
independently reviewable, which is why we can ship working machinery with zero
legal content.

### Compliance engine (`backend/apps/compliance/`)

Owns the verdict. Three guarantees, each covered by a test in
`apps/compliance/tests/test_engine.py`:

1. **No rules checked → never `COMPLIANT`.** Returns `REVIEW_REQUIRED`.
2. **An unverified rule can never produce a violation.** It can flag a product
   for human review; it cannot tell a user their package breaks the law.
3. **An unreadable photograph is never a missing declaration.** Extraction
   quality is checked before an absence is treated as a finding.

Result states:

| Result | Meaning |
|---|---|
| `COMPLIANT` | Every applicable rule was evaluated and passed. Not a certification. |
| `PARTIALLY_COMPLIANT` | Some rules failed, others could not be determined. |
| `NON_COMPLIANT` | Verified rules were not met, with evidence. |
| `REVIEW_REQUIRED` | Nothing could responsibly be concluded. **The default.** |

## Ownership and parallel work

Six developers, seven Django apps. Work inside your area; coordinate before
touching shared files.

| Area | Directory | Suggested branch | Status |
|---|---|---|---|
| Product upload & catalog API | `backend/apps/catalog/`, `backend/apps/images/` | `feature/product-upload` | |
| Image preprocessing | `ml/labelextract/preprocessing/` | `feature/image-processing` | First pass landed (orientation, grayscale, contrast). Deskew and perspective correction still open |
| OCR engine | `ml/labelextract/ocr/` | `feature/ocr-processing` | Tesseract 5 landed. A second engine for hard packaging is open |
| Field extraction | `ml/labelextract/fields/` | `feature/label-field-extraction` | English patterns landed. Layout-dependent declarations - name, brand, address - still open |
| Rule dataset | `rules/definitions/` | `feature/legal-rules-dataset` | |
| Rule engine & validators | `backend/apps/rules/checks/`, `backend/apps/compliance/` | `feature/compliance-rule-engine` | |
| Frontend UI | `frontend/src/` | `feature/frontend-dashboard` | |
| Authentication | `backend/apps/accounts/` | `feature/authentication` | |

**Shared files — announce changes before editing:**
`backend/config/settings.py`, `backend/config/api_v1.py`,
`ml/labelextract/contracts.py`, `backend/apps/core/`, `.env.example`.

`contracts.py` deserves particular care: it is the agreement between the ML and
backend teams. Changing it changes both sides at once.

## Deliberate non-decisions

Things we did **not** build, and why. Revisit each when its trigger fires.

| Not built | Why | Revisit when |
|---|---|---|
| Celery / Redis / task queue | Extraction still runs synchronously. Tesseract is fast enough on a cropped panel that a queue would be infrastructure ahead of the problem, and `run_extraction` is already the single place that would move behind one. | Measured latency puts an upload request over a few seconds - which is likely as soon as full-resolution phone photos are the input. **This is now the closest of these triggers to firing.** |
| Bounding-box mapping from preprocessed space back to source space | Preprocessing is geometry-preserving by default, so boxes already line up with the original. Building the mapping now would be code with no caller. | Resizing (`max_dimension`/`min_dimension`) is switched on, or a preprocessor that crops or deskews lands. Run metadata records both dimension sets so the mismatch is detectable rather than silent. |
| Docker | Adds a toolchain every teammate must learn to solve a problem we do not yet have. The README setup is a handful of standard commands. | Deployment, or environment drift across the team. |
| Token / JWT authentication | No endpoint in the base requires a user. Session auth plus deny-by-default permissions covers it safely. | `feature/authentication` adds real login. |
| Cloud object storage | Local `MEDIA_ROOT` is configurable via `DJANGO_MEDIA_ROOT`; the storage backend is a Django setting. | Deployment across more than one server. |
| Split settings (base/dev/prod) | The differences are a handful of values already read from the environment. | The environments genuinely diverge in structure. |
| Frontend state library | One page, one hook. Adding Redux now would be ceremony. | Cross-page shared state appears. |
| Ruff / Python linter | No Python linter. Nothing in the current code violates a rule it would catch, and it is one more toolchain for six people to install. ESLint was added for JavaScript because six people write JSX and hook-dependency bugs are silent. | Python style disagreements start costing review time. |
| `ProductClassifier` interface | No caller and no implementation. Its signature would be a guess. | `feature/product-classification`. |
| Extra models beyond the current nine | Adding schema later is a migration; adding half-designed schema now is a liability. | A feature actually needs it. |
| A `RuleOutcome` row per evaluated rule | Violations are recorded in full with a rule snapshot and evidence, so every *finding* is traceable. Which rules merely *passed* is stored only as counts on `ComplianceCheck`. Adding a row per rule per check multiplies write volume for data nothing currently reads. | An inspection report or enforcement dashboard needs to list the rules that passed, not just how many. `feature/compliance-analysis` owns it. |
| The five planned check types (`value_check`, `format_check`, `numeric_check`, `conditional_check`, `visual_check`) | Named in `apps.rules.checks.PLANNED_CHECK_TYPES` so the loader can say "planned, not built" instead of "unknown", but none is registered or callable. Writing five validators with no verified rule to exercise them would be guessing at signatures. | A verified rule needs one. The registry takes a validator plus its parameter validator, so each is a self-contained module. |
