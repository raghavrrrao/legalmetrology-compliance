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
value and bounding box, and each finding with its rule code, legal reference,
severity and evidence excerpt. `extraction.is_placeholder` says whether any
real recognition happened; `product_category_code` is `null` when the commodity
was not known.

**201 even when nothing could be read.** An unreadable photograph still
produces a stored, retrievable result whose verdict is `review_required` and
whose summary explains why. That is an outcome, not a failed request.

**400** for a missing file, a file the validators reject, an unknown
`category_code` or an unknown `view_type`.

### `GET /api/v1/compliance/<uuid>/`

The same body as above, for a result already computed. Exists so a result
survives a page reload and can be sent to a reviewer as a link. The id is a
UUID so holding one result's link does not let you walk to another's.

### Permissions on these two endpoints

Both follow the deny-by-default rule and require an authenticated user, unless
`DEMO_PUBLIC_ANALYSIS_API` is set. That setting **defaults to False** and is
intended only for a local demonstration, where no login screen exists yet. It
affects these two endpoints and nothing else, and uploads still go through
validation and anonymous throttling either way. See
`apps/compliance/api/permissions.py`.

## Planned endpoints

Not implemented. Listed so branches do not invent conflicting shapes — agree
the contract here in a PR before building it.

| Endpoint | Branch |
|---|---|
| `POST /api/v1/products/` | `feature/product-upload` |
| `POST /api/v1/extraction/` | `feature/ocr-processing` |
| `GET /api/v1/rules/` | `feature/rule-management` |

### What already exists behind them

`POST /api/v1/images/` and `GET /api/v1/compliance/<uuid>/` are now built and
documented above; `POST /api/v1/extraction/` is not. The services all of them
call are implemented and tested:

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

`POST /api/v1/images/` is accordingly a serializer for the multipart body, a
permission class, and a call to
`apps.compliance.services.analysis_service.analyse_upload`, which composes
`ingest_and_extract` with the compliance engine. **A view must not re-implement
validation or persistence**, and in particular must never write a
`ProductImage` without going through the ingestion service — that is the only
thing preventing an unvalidated file from reaching storage.

Two of the three decisions this section left open have now been made, for
`POST /api/v1/images/` only:

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
