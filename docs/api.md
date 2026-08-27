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

## Planned endpoints

Not implemented. Listed so branches do not invent conflicting shapes — agree
the contract here in a PR before building it.

| Endpoint | Branch |
|---|---|
| `POST /api/v1/products/` | `feature/product-upload` |
| `POST /api/v1/images/` | `feature/product-upload` |
| `POST /api/v1/extraction/` | `feature/ocr-processing` |
| `GET /api/v1/compliance/<id>/` | `feature/compliance-analysis` |
| `GET /api/v1/rules/` | `feature/rule-management` |

### What already exists behind them

The upload and extraction endpoints are the only missing layer, not the missing
work. The services they will call are implemented and tested:

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

So `POST /api/v1/images/` is a serializer for the multipart body, a permission
class, and a call to one of these. **A view must not re-implement validation or
persistence**, and in particular must never write a `ProductImage` without going
through the ingestion service — that is the only thing preventing an unvalidated
file from reaching storage.

Three decisions are still open and belong in the endpoint's PR, not here:

- **Synchronous or queued.** `run_extraction` runs inline today, which is fine
  for a placeholder engine and will not be for a real one. If the endpoint
  returns before extraction finishes, its response shape has to account for a
  run that is still `pending`/`running`.
- **Authentication.** `ProductImage.uploaded_by` is nullable and no endpoint
  currently authenticates. Whether uploads require a user is an unmade decision.
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
