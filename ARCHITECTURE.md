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
  apps.images.services          the only way an upload becomes a row:
    .ingestion                  validation cannot be skipped on this path
        │
        ▼
  ProductImage row              stored under a generated filename
        │
        ▼
  apps.extraction.services      the ONLY module that runs an ML engine
        │
        ▼
  labelextract.ExtractionPipeline
        │  preprocess ──▶ OCR ──▶ field extraction
        ▼
  ExtractionRun + ExtractedLabelField rows
        │                       readings, with confidence and bounding boxes
        ▼
  apps.compliance.services.engine   ◀── ProductApplicabilityDeclaration
        │                                   facts a PERSON stated, never
        │                                   inferred from the photograph
        ├─▶ which rules are candidates?  category + effective date + active
        ├─▶ do they GOVERN this package? rules 3 and 26, then each clause's
        │                                conditions - applicability.py
        ├─▶ evaluate the ones that do    via apps.rules.checks validators
        ├─▶ verified rules only          can produce a violation
        ▼
  ComplianceCheck + ComplianceFinding + ComplianceViolation + ComplianceEvidence
        │
        ▼
  /api/v1/... JSON response
        │
        ▼
  React UI: result, findings, evidence, the facts that were stated, and what
            could NOT be determined
```

**One compliance engine, several clients.** The React web app is a client of
that JSON, and a future React Native client is intended to be another one of the
same endpoints. Nothing in the API is shaped for a browser: there is no
server-rendered HTML, no session-only flow, and no web-only assumption in the
request or response bodies. A second client that reimplemented a rule would be
a second, unauditable answer, which is why the browser holds none.

```
React Web ─────┐
               ├── Django/DRF API ── OCR/extraction ── applicability
React Native ──┘                   ── compliance engine ── database
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

One service module per backend app, and they follow the same dependency
direction the backend does: `services/extractionService.js` owns the mapping of
a reading and knows nothing about compliance; `services/complianceService.js`
imports those mappers so the reading inside a result is mapped by exactly the
same code as the reading returned on its own. Compliance may depend on
extraction; extraction must never depend on compliance.

`hooks/useLabelAnalysis.js` runs the two-step flow (extract, then evaluate the
stored run) and holds the extraction run id, so a retried verdict re-evaluates
the reading already on screen instead of uploading the photograph again.

`utils/compliance.js` is the only file that maps a backend status to an
appearance, and it is presentation-only: partial lookups with a neutral
fallback, so a status this build has never seen renders as unrecognised rather
than inheriting a colour that would flatter it. It derives no verdict,
thresholds no confidence, and combines no statuses - that is the rule against
compliance logic in the browser, made checkable in one file. Its
`reviewReasonsFor` is the same rule applied to explanations: it turns flags the
response actually set into sentences, and returns nothing when the response
gives no reason. A plausible-sounding guess beside a legal outcome is worse
than silence.

**The legal condition catalogue is not in the browser either.** Several clauses
apply on facts no photograph can establish - whether the package contains bidi,
whether it is imported - and `components/ApplicabilityForm.jsx` asks about them.
Every question, clause reference and explanatory note it renders is served by
`GET /api/v1/compliance/applicability-conditions/`. A list of condition codes
written in JSX would be a copy of the legal catalogue that goes stale the moment
a clause is transcribed or a rule is deactivated, with nothing failing - so
there is none, and a component test asserts that a condition this build has
never heard of still renders.

Three properties of that form are safety properties rather than presentation
ones, and should survive a redesign:

1. **Unanswered is the default and is never "no".** An unstated fact stays
   unestablished, and the clause that turns on it reaches REVIEW REQUIRED. The
   form says so before the user answers anything.
2. **"Don't know" is a distinct, offerable answer.** It records that somebody
   was asked. It has the same effect on the engine as silence, and is never
   folded into "no".
3. **Re-evaluating never re-uploads.** After a verdict the same facts can be
   stated and the *same stored reading* judged again, so the reading on screen
   cannot change underneath the new verdict.

**A result screen shows three kinds of evidence under three headings**, because
collapsing any two of them misrepresents what the system knows: what the
pipeline *read* (`ExtractionPanel`), what a person *stated*
(`DeclarationsPanel`), and what the rules *concluded* (`FindingsList`). A
submitter's assertion that a package contains bidi is not a measurement, and a
screen that listed it beside the extracted net quantity would present it as one.

**There is no compliance score anywhere in the application**, and none may be
derived from the API. A percentage would imply that partial compliance with a
labelling requirement is partial credit. A test asserts that the only percentage
on a result screen is the OCR engine's own reported confidence in a reading.

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
- Every collection is paginated, with one shared class and an ordering that has
  a unique tie-breaker. A response whose size grows with the age of the
  deployment is not a contract.

### Service layer (`backend/apps/*/services/`)

Owns orchestration and business rules. Four services exist today:

- `images/services/ingestion.py` — validates an upload and stores it as a
  `ProductImage`, filling every column from what the bytes were measured to be
  rather than from what the upload claimed. It is the only path from an upload
  to a row, so nothing can reach extraction without having been validated.
- `extraction/services/extraction_service.py` — runs the OCR pipeline, checks
  what comes back against the contract, and persists the result.
  **The only backend module that reaches the ML runtime** — `registry`,
  `pipeline`, `exceptions`, and any engine behind them.
- `compliance/services/applicability.py` — decides whether a clause governs a
  package at all, from facts declared about the submission, **before** any
  validator runs. Three-valued: an unestablished fact yields "undetermined",
  never a verdict.
- `compliance/services/engine.py` — selects candidate rules, asks applicability
  which of them govern the package, evaluates those, records a finding for
  every outcome plus violations and evidence for the failures, and decides the
  overall result.
- `compliance/services/analysis_service.py` — composition only, with three
  entry points into that line: `analyse_upload(file)` runs all of it,
  `analyse_image(image)` re-reads a stored photograph, and `evaluate_run(run)`
  judges a reading that already exists without reading the photograph again.

`labelextract.contracts` is the one deliberate exception to that boundary. It
is a dependency-free vocabulary, not an implementation, and
`rules/checks/field_presence.py` imports `LabelFieldKey` from it so a rule and
a reading agree on what a field is called. Two vocabularies would drift; one
that lives in `ml/` does not. Both halves of the boundary are pinned by tests
in `apps/extraction/tests/test_extraction_integration.py`.

### Models (`backend/apps/*/models.py`)

Own persistence and data invariants. Notable decisions:

| Decision | Reason |
|---|---|
| UUID primary keys on `Product`, `ProductImage`, `ExtractionRun`, `ComplianceCheck` | These IDs appear in URLs. Sequential integers would let one user enumerate another's submissions. |
| Label declarations live in `extraction`, not on `Product` | A declaration is a *reading from a photograph*, with a confidence and a source. Copying it onto `Product` would turn evidence into an unsourced assertion. |
| `ExtractionRun` is a FK to image, not a OneToOne | Re-running a better engine must not destroy the readings that existing compliance results cite. |
| `ComplianceCheck` is a FK, not a OneToOne | Rules change; re-evaluating adds a result rather than rewriting history. |
| `ComplianceViolation` snapshots the rule's severity and reference | An amended rule must not silently change what a past finding meant. |
| `ComplianceFinding` records every rule examined, `ComplianceViolation` only the failures | They answer different questions. "What is wrong with this package?" is the violation list; "what was actually checked, and on what evidence?" is the finding list, and a user needs the second before they can trust the first. A pass and an undecidable rule have no violation to hang off. |
| `ComplianceFinding.extracted_confidence` is a snapshot column, not a join | The confidence behind a finding must survive the reading being deleted, and reaching it through the foreign key would be a query per finding on the write paths. |
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
4. **Product classification** — what kind of product is this. A TF-IDF + logistic-regression baseline over the recognised text, reporting a category the applicability layer already speaks or UNKNOWN. Consumed by nothing in the decision path yet; see `docs/ml/product-classification.md`.
5. **Compliance reasoning** — is this correct. **Not ML. Lives in the backend.**

OCR and compliance reasoning are not the same thing and must never be merged.
An OCR engine reads characters; it has no opinion about the law.

### Rules (`rules/` + `backend/apps/rules/`)

Owns the compliance requirements, as reviewable data. **Two layers**, and the
distinction between them is load-bearing.

**The executable layer** — what the engine runs.

- `rules/definitions/*.json` — the rules, in Git, reviewed via pull request.
- `apps/rules/loader.py` — strict validation and idempotent import.
- `apps/rules/checks/` — validators, which answer *mechanical* questions.
- `apps/rules/models.py` — `ComplianceRule`, including `source_status`.

The split that makes this work: a **validator** asks a factual question ("was
this declaration found?"). A **rule row** supplies the legal claim ("this
declaration is required for this commodity"). Machinery and legal content are
independently reviewable, which is why we can ship working machinery with zero
legal content.

**The legal framework** — what the Rules require, evaluable or not.

- `rules/framework/*.json` — instruments, applicability conditions, and rules
  1–34 with their versioned clause-level requirements.
- `apps/rules/framework_loader.py` + `manage.py load_legal_framework`.
- `apps/rules/models.py` — `LegalInstrument`, `LegalRule`, `RuleRequirement`,
  `ApplicabilityCondition`, `RequirementApplicability`.

The executable layer cannot honestly represent rule 22 (maximum permissible
error), rules 27–30 (registration) or rule 32 (penalties): they are real
obligations that **no photograph decides**. Recording them only as executable
rules would mean either hiding them — leaving the widest compliance risk
invisible — or having the engine evaluate a JPEG against a weighing obligation.

So every requirement carries a `detection_method` saying what evidence could
settle it *at all*. Anything outside `ocr`/`cv`/`ocr_cv` reaches the user as
`REVIEW_REQUIRED`, not because the engine is immature but because the evidence
is not in the building. Requirements are **versioned**: an amendment adds a row
and never edits one, so a finding recorded last year keeps citing the text that
was in force then.

**Recording a requirement does not mean it is evaluated.** 69 requirements are
on record; 8 of them are reached by 11 executable rules, and every one of those
tests less than its clause requires. See
[`rules/FRAMEWORK.md`](rules/FRAMEWORK.md) and
[`rules/README.md`](rules/README.md) for what each does and does not cover.

### Compliance engine (`backend/apps/compliance/`)

Owns the verdict. The pipeline, in order:

```
Product + ExtractionRun
    -> applicability      rules 3 and 26, then per clause    (applicability.py)
    -> evaluate           the rules that actually govern it  (rules/checks/)
    -> findings           every outcome, with its legal context
    -> violations         failures against verified rules only
    -> overall result
```

**Applicability is settled before any validator runs.** A rule that does not
govern a package must not read its label at all — evaluating and discarding
would still let a misread declaration reach a finding on a package the clause
never covered.

Four guarantees, each covered by a test:

1. **No rules checked → never `COMPLIANT`.** Returns `REVIEW_REQUIRED`. This
   now covers the case where every rule was ruled out by an exemption: a set of
   exemptions is not a clean bill of health.
2. **An unverified rule can never produce a violation.** It can flag a product
   for human review; it cannot tell a user their package breaks the law.
3. **An unreadable photograph is never a missing declaration.** Extraction
   quality is checked before an absence is treated as a finding.
4. **An unestablished fact never produces a verdict.** A clause turning on a
   condition nobody declared is inconclusive — not applied, not excused.
5. **A reading nobody trusts never produces a violation.** The three checks
   that read a declaration's *normalised* value rather than merely noting it
   exists — the consumer-care elements, whether a date resolves to a month and
   a year, whether a price is declared exclusive of taxes — require both the
   extractor to have committed to an interpretation and the engine not to have
   reported a low confidence. Either signal against, and the outcome is
   inconclusive. The gate lives in `rules/checks/evidence.py`, and its
   threshold can only ever move a result from failed to inconclusive, never the
   other way.

**Presence and manner-of-declaration are separate rules against one clause.**
`ComplianceRule.rule_requirement` is many-to-one for that reason: rule 6(2) has
one rule asking whether a consumer-care declaration was read and another asking
whether it states a telephone number and an e-mail address, so a package that
declares half of what it owes produces one precise finding rather than one
blurred verdict. A manner-of-declaration rule whose declaration is **absent**
reports inconclusive and defers to the presence rule, so one missing
declaration is one violation and not two.

Result states:

| Result | Meaning |
|---|---|
| `COMPLIANT` | Every applicable rule was evaluated and passed. Not a certification. |
| `PARTIALLY_COMPLIANT` | Some rules failed, others could not be determined. |
| `NON_COMPLIANT` | Verified rules were not met, with evidence. |
| `REVIEW_REQUIRED` | Nothing could responsibly be concluded. **The default.** |

Per-finding status is four-valued: `passed`, `failed`, `inconclusive` and
`not_applicable`. The last means the rule does not govern this package, so
nothing about its declarations was examined — counted separately from
`rules_evaluated`, because folding it into `passed` would let exemptions read
as compliance.

## Deployment topology

The layer diagram above is the code. This is where it runs.

```
   React web client                        React Native client
   static bundle, hosted separately        (not built - later phase)
          │                                        │
          │  HTTPS, VITE_API_BASE_URL              │  same API, same verdicts
          └──────────────────┬─────────────────────┘
                             ▼
   ┌──────────────────────────────────────────────────────┐
   │  ONE container  (Dockerfile)                         │
   │                                                      │
   │  gunicorn ── Django/DRF ── services ── rule engine   │
   │      │                          │                    │
   │  WhiteNoise                  labelextract            │
   │  (STATIC_ROOT only)          └─ tesseract binary     │
   └──────────────────────────────────┬───────────────────┘
                                      ▼
                              PostgreSQL (managed)
```

Three properties of this shape are deliberate and worth stating, because each
is a decision that could be undone by accident:

**There is exactly one compliance engine, and it is on the server.** Every
client - the React web app today, a React Native app later - asks the same API
and gets the same verdict from the same rule rows. A rule evaluated on a device
would be a second engine that could disagree with the first about what the law
requires, which is the one kind of drift this project cannot tolerate. It is
also why the mobile client is a later phase and not a parallel one: there is
nothing to build against until the API is deployed and stable.

**OCR runs inside the same process as the API.** Extraction is a synchronous
subprocess call to `tesseract`, so the container needs the binary and the
request waits for it. That is why the image is built from a Dockerfile rather
than by a Python builder, why gunicorn uses threads, and why a queue is the
nearest of the deferred decisions below to being needed.

**The frontend is a static bundle with the API origin compiled in.** It shares
no runtime with the backend and holds no secret. Moving the API means rebuilding
the frontend, not reconfiguring it - see `docs/deployment.md`.

Operational detail - variables, initialisation order, media persistence,
throttling and worker count - lives in [docs/deployment.md](docs/deployment.md)
rather than here.

## Ownership and parallel work

Six developers, seven Django apps. Work inside your area; coordinate before
touching shared files.

| Area | Directory | Suggested branch | Status |
|---|---|---|---|
| Product upload & catalog API | `backend/apps/catalog/`, `backend/apps/images/` | `feature/product-upload` | |
| Image preprocessing | `ml/labelextract/preprocessing/` | `feature/image-processing` | First pass landed (orientation, grayscale, contrast). Deskew and perspective correction still open |
| OCR engine | `ml/labelextract/ocr/` | `feature/ocr-processing` | Tesseract 5 landed. A second engine for hard packaging is open |
| Field extraction | `ml/labelextract/fields/` | `feature/label-field-extraction` | English patterns landed. Layout-dependent declarations - name, brand, address - still open |
| Rule dataset | `rules/definitions/` | `feature/legal-rules-dataset` | Twelve rules from rules 6 and 13 landed; eleven active, `LM-PC-0002` inactive pending extraction support. Rules 7-13 are otherwise blocked on evidence the pipeline cannot supply or on clause text nobody has transcribed - see `rules/INVENTORY.md`. Legal counter-review still open - see `rules/SOURCES.md` |
| Rule engine & validators | `backend/apps/rules/checks/`, `backend/apps/compliance/` | `feature/compliance-rule-engine` | |
| Frontend UI | `frontend/src/` | `feature/frontend-dashboard` | Scan, result, permalink and inspection-history screens landed against the real API, with the applicability declaration form and the full finding trace. Authentication UI and rule browsing are still open — neither has a backing endpoint yet |
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
| ~~Docker~~ **- now built, for deployment only** | The trigger fired: deployment. There is a production `Dockerfile` because Tesseract is a system binary that `pip` cannot install, so an automatic Python builder produces an image that looks configured and reads nothing. It is **not** part of local development - the README setup is still a handful of standard commands, no teammate needs Docker installed, and no `docker-compose.yml` exists. | It would be needed for local development too. It is not today. |
| Token / JWT authentication | No endpoint in the base requires a user. Session auth plus deny-by-default permissions covers it safely. | `feature/authentication` adds real login. |
| Cloud object storage | Local `MEDIA_ROOT` is configurable via `DJANGO_MEDIA_ROOT`. **The storage backend is no longer merely a Django setting, and this row is now a known deployment blocker rather than a deferral:** `extraction_service.build_image_ref` opens `ProductImage.image.path`, and a remote backend raises `NotImplementedError` for `.path`, so every extraction would fail as `invalid_image`. Adopting object storage means changing that function to stream bytes first. On a platform with an ephemeral filesystem the consequence today is that uploaded photographs are lost on each deploy unless a volume is mounted. | Uploaded evidence has to outlive a deploy, or more than one replica serves traffic. `docs/deployment.md` states the interim position. |
| Split settings (base/dev/prod) | The differences are a handful of values already read from the environment. | The environments genuinely diverge in structure. |
| Frontend state library | Three pages, one hook each, and the only shared state is a result the API can be asked for again by id. Adding Redux now would be ceremony. | State has to outlive a route change, or two screens must stay in step. |
| Ruff / Python linter | No Python linter. Nothing in the current code violates a rule it would catch, and it is one more toolchain for six people to install. ESLint was added for JavaScript because six people write JSX and hook-dependency bugs are silent. | Python style disagreements start costing review time. |
| ~~`ProductClassifier` interface~~ **- now built** | The trigger fired. `labelextract.interfaces.ProductClassifier` runs as the optional last stage of `ExtractionPipeline`; `tesseract` 0.4.0 wires the shipped `tfidf-logreg` 0.1.0. Its output is an observation in run metadata and the API, and **nothing in applicability or the rule engine reads it** — that wiring is the next step, gated on human confirmation and on data the project does not yet have. | A calibrated classifier and a confirmation UI exist. |
| Extra models beyond the current nine | Adding schema later is a migration; adding half-designed schema now is a liability. | A feature actually needs it. |
| A `RuleOutcome` row per evaluated rule | Violations are recorded in full with a rule snapshot and evidence, so every *finding* is traceable. Which rules merely *passed* is stored only as counts on `ComplianceCheck`. Adding a row per rule per check multiplies write volume for data nothing currently reads. | An inspection report or enforcement dashboard needs to list the rules that passed, not just how many. `feature/compliance-analysis` owns it. |
| The five planned check types (`value_check`, `format_check`, `numeric_check`, `conditional_check`, `visual_check`) | Named in `apps.rules.checks.PLANNED_CHECK_TYPES` so the loader can say "planned, not built" instead of "unknown", but none is registered or callable. Writing five validators with no verified rule to exercise them would be guessing at signatures. Nothing since has needed the generic names: each clause that could be automated got a validator shaped to that clause, which is why the registry holds `month_year_declaration` rather than a general `format_check`. | A verified rule needs one. The registry takes a validator plus its parameter validator, so each is a self-contained module. |
| A `visual_check`, and with it rules 7, 8(1) and 9(1)(b) | Rule 7's Table-I heights are absolute millimetres and a photograph carries no scale; rule 8(1)'s clear-space proviso and rule 7(3)'s one-third ratio *are* scale-free and computable from bounding boxes, but both need to know which face is the principal display panel, which no current input settles. Claiming a typography measurement from OCR alone would be inventing evidence. | A calibrated scale reference, or a declared principal display panel. |
| Rules 11(2)-(4), 12(6) and 13(2)-(3) | Their `verbatim_text` in `rules/framework/rules.json` is **empty or summarised** — the source records them by effect rather than quotation, and rule 12(6)'s candidate prohibited-word list is recorded there as coming from the *pre-2011* text. Coding a check against a summary would write the requirement, and coding that word list would enforce a repealed instrument. | A named reviewer transcribes the clauses from the source. |
| Rule 9(4), the language requirement | Script detection is tractable, but the OCR is English-only, so a wholly Hindi label reads as *unreadable* rather than as compliant. Reporting that as a violation would be exactly backwards. | The extractor handles Devanagari. |
