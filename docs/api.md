# API conventions

Base URL: `/api/v1/`

## Versioning

Every endpoint lives under a version prefix. Within a version:

- **Additive changes are allowed.** New endpoints, new optional request fields,
  new response fields.
- **Breaking changes are not.** Removing or renaming a response field, changing
  a field's type, or making an optional request field required means `/api/v2/`.

A new version is a new namespace in `backend/config/urls.py`, not edits to v1.
Existing clients keep working.

Routing lives in `backend/config/api_v1.py`; each app contributes its own
`api/urls.py`. Route names are namespaced as `v1:<name>` — e.g.
`reverse("v1:health")`.

## Trailing slashes

**Required.** `/api/v1/health/`, not `/api/v1/health`.

Django's `APPEND_SLASH` redirects a missing slash, and a redirect turns a POST
into a GET, silently dropping the body. The frontend's `apiClient` builds URLs
consistently, so this only bites hand-written requests.

## Authentication

Session authentication. Permissions **deny by default** — every endpoint
requires an authenticated user unless it explicitly opts out with
`permission_classes = [AllowAny]`. Forgetting to think about permissions
therefore fails closed.

`/api/v1/health/` is the only public endpoint today.

Unsafe methods need Django's CSRF token in an `X-CSRFToken` header. The
frontend `apiClient` reads the cookie and attaches it automatically.

## Error envelope

**Every** failure returns the same shape, at every status code:

```json
{
  "error": {
    "code": "validation_error",
    "message": "The submitted data was not valid.",
    "details": { "image": ["This field is required."] }
  }
}
```

| Field | Contract |
|---|---|
| `code` | Stable, machine-readable. **Branch on this**, never on `message`. |
| `message` | Human-readable and safe to display to a user. |
| `details` | Optional structured context. May be `null`. |

For validation errors, `message` stays generic and the per-field errors go in
`details` — so the UI can show one banner plus inline field messages.

Implemented by `apps/core/api/exceptions.py`, wired in via DRF's
`EXCEPTION_HANDLER`.

### Codes

| Code | HTTP | Meaning |
|---|---|---|
| `validation_error` | 400 | Request data failed validation. `details` holds field errors. |
| `parse_error` | 400 | Body was not parseable. |
| `not_authenticated` | 401 | No credentials supplied. |
| `authentication_failed` | 401 | Credentials were rejected. |
| `permission_denied` | 403 | Authenticated, but not allowed. |
| `not_found` | 404 | No such resource, or no such route. |
| `method_not_allowed` | 405 | Wrong HTTP method for this endpoint. |
| `unsupported_media_type` | 415 | Wrong `Content-Type`. |
| `rate_limited` | 429 | Throttled. `details.retry_after_seconds` says how long to wait. |

Unhandled server errors deliberately return a plain 500, not a 200 carrying an
error body. A failure stays a failure at the HTTP level, and the traceback is
logged server-side rather than returned.

Unmatched paths under `/api/v1/` are caught by `ApiNotFoundView` so they return
the JSON envelope rather than Django's HTML 404 page.

## Throttling

DRF's built-in rate limiting, using the local-memory cache — no Redis.

| Scope | Default | Setting |
|---|---|---|
| Anonymous | 30/min | `API_THROTTLE_ANON` |
| Authenticated | 120/min | `API_THROTTLE_USER` |

`/api/v1/health/` is exempt: a health check that gets throttled reports a false
outage, and polling is the point of it.

> Local-memory throttling is **per process**. With multiple workers the
> effective limit multiplies. That is fine for development and for a
> demonstration; a real deployment needs a shared cache. Noted rather than
> pre-built.

## CORS

Explicit origins only, from `CORS_ALLOWED_ORIGINS`. `CORS_ALLOW_ALL_ORIGINS` is
never enabled, including in development, so a permissive setting cannot survive
into a deployment by accident.

`CORS_ALLOW_CREDENTIALS` is on so the session cookie travels from the Vite dev
server on port 5173.

## Endpoints

### `GET /api/v1/health/`

Public. Liveness plus dependency status.

**200** when everything is up, **503** when any dependency is down — so an
uptime check can rely on the status code alone.

```json
{
  "status": "ok",
  "api_version": "v1",
  "dependencies": {
    "database": "ok",
    "extraction_engine": "ok"
  },
  "extraction_engine": {
    "name": "null-engine",
    "version": "0.1.0",
    "is_placeholder": true
  },
  "compliance_rules": {
    "active_total": 0,
    "verified": 0,
    "unverified": 0
  }
}
```

Two fields are worth understanding:

- **`extraction_engine.is_placeholder`** — `true` means no OCR engine is
  installed and the pipeline reads no text. The UI must surface this rather
  than presenting wiring output as a reading.
- **`compliance_rules.verified`** — only verified rules can make a product
  non-compliant. While this is `0`, nothing can be found non-compliant.

The endpoint reports *whether* each dependency answered, never *why* it did
not. Error detail is logged server-side; the response says only `unavailable`,
so it stays useful to the team without being useful to a scanner.

### `POST /api/v1/images/`

Upload a label photograph; receive the finished compliance result.

Runs the whole flow inline - validate, store, OCR, extract, normalise,
evaluate - and returns **201** with the complete `ComplianceCheck`. Extraction
measures at a ~2.2 s median on the configured Tesseract pipeline
(docs/evaluation-results.md), so there is nothing to poll. When that becomes
slow enough to need a queue, `run_extraction` moves behind it and this response
gains a `pending` shape additively.

`multipart/form-data`:

| Field | Required | Notes |
|---|---|---|
| `image` | yes | The photograph. Validated by `apps.images.validators` in full. |
| `view_type` | no | A `ProductImage.ViewType` value. Defaults to `unspecified`. |
| `category_code` | no | A `ProductCategory.code`. Determines which rules apply. An unknown code is a 400, never silently ignored - dropping it would produce a "category not known" result indistinguishable from omitting it. |

**201** carries the verdict (`result`), the engine's plain-language
explanation (`summary`), every declaration that was read with its normalised
value and bounding box, and the two finding lists described under
[Findings and violations](#findings-and-violations) below.
`extraction.is_placeholder` says whether any real recognition happened;
`product_category_code` is `null` when the commodity was not known.

**201 even when nothing could be read.** An unreadable photograph still
produces a stored, retrievable result whose verdict is `review_required` and
whose summary explains why. That is an outcome, not a failed request.

**400** for a missing file, a file the validators reject, an unknown
`category_code` or an unknown `view_type`.

### `POST /api/v1/extraction/`

Upload a label photograph; receive **what was read off it**, and nothing more.

The same upload and the same pipeline as the endpoint above, stopping one stage
earlier:

```
image -> validate -> OCR -> field extraction -> normalisation -> [this response]
                                             -> rule engine -> findings -> verdict
```

That separation is the point of the endpoint, not a limitation of it. A reading
is an observation about a photograph; a verdict is a claim about a package under
the Legal Metrology (Packaged Commodities) Rules, 2011. Only the rule engine
makes the second, and only from verified rules. Use this endpoint when you want
the first on its own — evaluating the extractor, checking what a photograph
actually contains, or building a UI step that shows the reading before any
determination is offered.

`multipart/form-data`:

| Field | Required | Notes |
|---|---|---|
| `image` | yes | The photograph. Validated by `apps.images.validators` in full — the same path as `POST /api/v1/images/`. |
| `view_type` | no | A `ProductImage.ViewType` value. Defaults to `unspecified`. |

There is deliberately **no `category_code`**. A category selects which rules
apply, and no rule is consulted here. Nothing is created but a `ProductImage`
and an `ExtractionRun`: no `Product`, no `ComplianceCheck`.

**201** carries the run and the stored image:

```json
{
  "id": "…",
  "engine_name": "tesseract",
  "engine_version": "0.2.0",
  "is_placeholder": false,
  "status": "completed",
  "produced_usable_output": true,
  "processing_ms": 2202,
  "recognised_text": "…",
  "error_code": "",
  "error_message": "",
  "fields_read": [
    {
      "field_key": "net_quantity",
      "raw_value": "Net Qty: 500 g",
      "normalized_value": {"quantity": 500, "unit": "g", "uncertain": false},
      "confidence": 0.87,
      "bounding_box": {"x": 4, "y": 4, "width": 300, "height": 18}
    }
  ],
  "unread_declarations": [],
  "image": {"id": "…", "image_format": "png", "width": 1024, "height": 768, "…": "…"}
}
```

The body has no `result`, `summary` or `violations` key and must never grow
one. A test asserts their absence.

Four fields are load-bearing and a client should not ignore any of them:

- **`produced_usable_output`** — false means the label was not read well enough
  to be judged against. An absent declaration in that case says nothing about
  the package.
- **`is_placeholder`** — true means no recognition happened at all. This is the
  shipped default until an OCR engine is selected in `.env`.
- **`confidence`** — `null` means the engine did not report one. It is not zero
  and not certainty.
- **`unread_declarations`** — declarations the label named whose values could
  not be read. Empty means "the engine reported none", not "everything was
  read". This is the difference between asking for a better photograph and
  reporting a possible contravention.

**201 even when nothing could be read.** An unreadable photograph produces a
stored run with `status` `empty` or `failed`, `produced_usable_output` false,
and an `error_code` saying which. That is an outcome, not a failed request.

**400** for a missing file, an unknown `view_type`, or a file the validators
reject — too large, not a decodable image, a format outside the allowlist, or a
decompression bomb. Nothing is stored and no run is created.

**500** only for an engine that ran and then broke its own output contract,
which is a bug rather than an outcome. The failed run is recorded first, so the
image does not sit in `processing` forever, and the exception is then re-raised
rather than filed away as "the photograph was unreadable". The client gets the
generic 500 body; the traceback is logged server-side and never returned.

### `POST /api/v1/compliance/`

Evaluate a reading that already exists against the applicable rules.

The second half of the two-step path. `POST /api/v1/extraction/` answers "what
does the label say?"; this answers "what do the rules make of that?" — without
reading the photograph again.

```
POST /api/v1/extraction/  ->  ExtractionRun id  ->  POST /api/v1/compliance/
```

Re-reading would not merely be slow: OCR is not guaranteed identical across
runs and the engine may be reconfigured in between, so a finding could cite a
value the user was never shown. Evaluating the stored run is what keeps the
reading the user saw and the verdict they were given based on the same
evidence.

`application/json`:

| Field | Required | Notes |
|---|---|---|
| `extraction_run_id` | yes | The reading to evaluate, as returned by `POST /api/v1/extraction/`. An unknown id is a 400. |
| `category_code` | no | A `ProductCategory.code`. Determines which rules apply. Ignored when the run's image is already linked to a product — that product's category wins. An unknown code is a 400, never silently ignored. |

**There is no rule, check-type, severity, engine or threshold parameter, and
there must never be one.** Applicability is answered by
`engine.applicable_rules` from the loaded rule set and the commodity's category
alone. A verdict a client could steer by choosing its own rules would be worth
nothing.

**201** with the same `ComplianceCheck` body `POST /api/v1/images/` returns.
201 rather than 200 because an evaluation is a new record: evaluating the same
run twice creates two checks, which is how a result from before a rule was
loaded stays comparable with one from after.

**201 even when no conclusion could be drawn.** An unreadable reading, an
unknown commodity category, or no loaded rules each produce a stored result
whose verdict is `review_required` and whose summary says which of those it
was.

**400** for a missing, malformed or unknown `extraction_run_id`, or an unknown
`category_code`.

### `GET /api/v1/compliance/<uuid>/`

The same body as above, for a result already computed. Exists so a result
survives a page reload and can be sent to a reviewer as a link. The id is a
UUID so holding one result's link does not let you walk to another's.

### Findings and violations

A compliance result carries **two** lists, and they are not the same list.

| Key | What it is |
|---|---|
| `findings` | One entry per rule that was **examined**, whatever it concluded — `passed`, `failed` or `inconclusive`. |
| `violations` | One entry per rule the package was found to **fail**. A subset of the above; each `findings[].violation` holds the id of its violation, or `null`. |

`violations` answers "what is wrong with this package?". `findings` answers
"what was actually checked, and on what evidence?" — which a user needs before
they can trust the first answer, and which was previously only available as the
`rules_passed` / `rules_failed` / `rules_inconclusive` counters.

Each finding carries:

| Field | Meaning |
|---|---|
| `rule_code`, `title`, `requirement` | What was required, in the rule's own words. Snapshotted, so an amended rule cannot change what a past finding meant. |
| `legal_reference` | Where that requirement comes from. |
| `check_type` | Which registered deterministic check asked the question. |
| `field_key` | Which declaration it concerns. |
| `status` | `passed` / `failed` / `inconclusive`. |
| `message` | What was observed and why, in plain language. |
| `evidence_excerpt`, `bounding_box` | What was read, and where on the image. |
| `extracted_confidence` | How sure the OCR/ML layer was about the reading behind this finding. |
| `severity` | Triage ranking only. It carries **no legal weight** — `rules/SCHEMA.md` says so, and the UI must not present it as one. |
| `downgraded_from_failed` | The check failed, but the rule is not verified against the authoritative legal text, so the engine recorded it as inconclusive rather than as a violation. |
| `details` | Validator diagnostics. Shape is validator-specific. |
| `violation` | Id of the violation this became, or `null`. |

Three of these are easy to misread:

- **`inconclusive` is not a soft fail.** It means the check could not be
  decided, usually because the photograph was not readable. Treating it as
  either a pass or a violation is the most damaging thing a client can do with
  this data — it is the difference between "your package is illegal" and "we
  could not read your photo".
- **`extracted_confidence` is recorded, not enforced.** No rule in this
  repository conditions its outcome on it, so a `passed` finding built on a
  low-confidence reading is still `passed`. The number is exposed precisely so
  that cannot happen silently: a client showing a finding should show what the
  reading behind it was worth. `null` means the OCR engine did not report a
  confidence, and is **not** zero.
- **`downgraded_from_failed` is a legal safeguard firing**, not a data problem.
  An unverified rule can flag a package for human review; it can never tell a
  user their package breaks the law.

### Which endpoints the frontend actually calls

Recorded here because the choice is not obvious from the endpoint list, and
because a second client should make the same one.

The scan screen uses the **two-step path**, not the one-shot one:

```
POST /api/v1/extraction/   ->  ExtractionRun id
POST /api/v1/compliance/   ->  ComplianceCheck   (that id, no re-upload)
```

It needs the reading on screen next to the verdict, so that a reviewer can
check a finding against the text it was drawn from. `POST /api/v1/images/`
returns both in one response and remains supported - `analyseImage` in
`frontend/src/services/complianceService.js` still calls it - but a client that
displays the reading should evaluate the stored run rather than upload twice.

`GET /api/v1/compliance/<uuid>/` backs the frontend route `/result/<uuid>`,
which is what makes a result reloadable and sendable as a link.

One consequence of the response shape is worth stating, because it looks like a
gap and is not: **`ProductImageSerializer` exposes no URL, and no endpoint
serves the stored bytes back.** The frontend therefore draws its evidence
overlay over the `File` the user selected, using `image.width` / `image.height`
as the coordinate space that `bounding_box` is expressed in. A result opened
from a link shows the findings and their excerpts, and says the photograph is
not available on that device rather than showing an empty frame.

### Permissions on the four analysis endpoints

All four — upload-and-analyse, upload-and-extract, evaluate-a-reading, and
reading a stored result back — follow the deny-by-default rule and require an authenticated user, unless
`DEMO_PUBLIC_ANALYSIS_API` is set. That setting **defaults to False** and is
intended only for a local demonstration, where no login screen exists yet. It
affects these four endpoints and nothing else, and uploads still go through
validation and anonymous throttling either way. See
`apps/core/api/permissions.py` (re-exported from
`apps/compliance/api/permissions.py`, which is where it used to live).

## Planned endpoints

Not implemented. Listed so branches do not invent conflicting shapes — agree
the contract here in a PR before building it.

| Endpoint | Branch |
|---|---|
| `POST /api/v1/products/` | `feature/product-upload` |
| `GET /api/v1/rules/` | `feature/rule-management` |

### What already exists behind them

All three of `POST /api/v1/images/`, `POST /api/v1/extraction/` and
`GET /api/v1/compliance/<uuid>/` are now built and documented above. The
services they call are implemented and tested:

- `apps.images.services.ingestion.ingest_product_image(upload, ...)` — validates
  and stores an upload, returning a `ProductImage`. Raises Django
  `ValidationError` with a `code` (`unsupported_extension`, `file_too_large`,
  `undecodable_image`, …). The standard error envelope already turns that into a
  400 — but note it does **not** currently surface the code:
  `api_exception_handler` converts a Django `ValidationError` through
  `exc.messages`, so every rejection reaches the client as `validation_error`
  with the reason in `details`, and none of the codes above appear in the Codes
  table on this page.
- `apps.extraction.services.extraction_service.run_extraction(image, ...)` —
  runs the pipeline and persists an `ExtractionRun` plus its
  `ExtractedLabelField` rows.
- `apps.extraction.services.extraction_service.ingest_and_extract(upload, ...)` —
  both, returning an `ExtractionOutcome(image, run)`.

`POST /api/v1/extraction/` is accordingly a serializer for the multipart body,
a permission class, and a call to `ingest_and_extract`. `POST /api/v1/images/`
is the same three things plus a call to
`apps.compliance.services.analysis_service.analyse_upload`, which composes
`ingest_and_extract` with the compliance engine. **A view must not re-implement
validation or persistence**, and in particular must never write a
`ProductImage` without going through the ingestion service — that is the only
thing preventing an unvalidated file from reaching storage.

Two of the three decisions this section left open have now been made, and both
apply to `POST /api/v1/images/` and `POST /api/v1/extraction/` alike:

- **Synchronous or queued** — decided: synchronous. `run_extraction` runs
  inline, which measures at a ~2.2 s median on the configured Tesseract
  pipeline. When that becomes too slow, `run_extraction` moves behind a queue
  and the response gains a `pending` shape additively.
- **Authentication** — decided: authenticated by default, with an explicit,
  default-off `DEMO_PUBLIC_ANALYSIS_API` switch for a local demonstration.
  `ProductImage.uploaded_by` is filled in when there is a user and left null
  when there is not.

One remains open, because it is a change to shared error handling rather than
to one endpoint:

- **Whether rejection reasons reach the client.** As above, the envelope
  flattens every upload rejection to `validation_error`, so the UI cannot today
  tell "convert this file" from "this file is corrupt". Surfacing the validator
  codes means teaching `api_exception_handler` to read `ValidationError.code`
  and adding them to the Codes table — a change to shared error handling, which
  is why it is not made here.

One constraint is **not** open, and the endpoint must respect it:
`run_extraction` deliberately manages its own transactions so that a failed
extraction still leaves a `failed` `ExtractionRun` behind. Enabling
`ATOMIC_REQUESTS`, or wrapping the call in the view's own `transaction.atomic()`,
discards that record along with the exception — the image is then left in
`processing` with nothing explaining why.

## Conventions for new endpoints

- Plural, lowercase, hyphenated collection names; trailing slash.
- Resource IDs in paths are UUIDs.
- Request and response bodies use `snake_case`. The frontend service layer maps
  to `camelCase` at the boundary, in one place per endpoint.
- Return `201` with the created object for creates; `204` with no body for
  deletes.
- Validation belongs in serializers. Business logic belongs in
  `apps/*/services/`, never in a view.
- Never return a partially-built object with fabricated fields to make a
  response look complete. Omit what is not known, or return `null`.
