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

## Pagination

Every endpoint that returns a **collection** is paginated, with DRF's
page-number style and one shared class,
`apps.core.api.pagination.DefaultPageNumberPagination`. An unpaginated
collection is not an option: it is a response whose size is decided by how long
the system has been running.

| Query parameter | Default | Notes |
|---|---|---|
| `page` | 1 | 1-based. Out of range or non-numeric is a **404** with code `not_found`. |
| `page_size` | 20 | Capped at **100**. A malformed value (`abc`, `0`, `-1`) falls back to the default rather than erroring — a client that mistypes a page size still wants its results. |

The body is always the same four keys:

```json
{
  "count": 42,
  "next": "https://host/api/v1/compliance/?page=3",
  "previous": "https://host/api/v1/compliance/?page=1",
  "results": []
}
```

- **`count`** is how many results exist in total, not how many this page holds.
- **`next` / `previous`** are absolute URLs, or `null` at either end. Follow them
  rather than building page numbers, so a later change to the page size does not
  break a client.
- **`results`** is always a list, and is empty — never `null`, never a 404 — when
  there is nothing to return.

**A paginated endpoint must have a total order.** Sorting only by a timestamp is
not one: timestamps collide, and an unstable sort under pagination shows one row
on two pages and omits another, silently. Every list endpoint orders by its sort
key *and* a unique tie-breaker.

The class is not registered as `DEFAULT_PAGINATION_CLASS`; each list view names
it, so a response shape is a property of the endpoint rather than of a global.

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
    "is_placeholder": true,
    "available": true,
    "detail": ""
  },
  "compliance_rules": {
    "active_total": 0,
    "verified": 0,
    "unverified": 0,
    "applicability_conditions": 0
  }
}
```

Four fields are worth understanding:

- **`extraction_engine.is_placeholder`** — `true` means no OCR engine is
  installed and the pipeline reads no text. The UI must surface this rather
  than presenting wiring output as a reading.
- **`extraction_engine.available`** — whether the configured pipeline can
  actually run here. For the Tesseract pipeline this resolves `pytesseract`
  **and** calls the `tesseract` binary, so it is `false` on a deployment whose
  image lacks the binary. That is a different failure from `is_placeholder`,
  and the only one of the two a deployment usually hits: the pipeline is real,
  so `is_placeholder` is `false` and everything looks configured, while every
  upload fails. `available: false` makes the endpoint answer **503**, and
  `detail` carries a short code (`engine_not_available`, `pipeline_not_found`)
  and never a path, a version string or a traceback.

  A deployment genuinely doing OCR reports `is_placeholder: false` **and**
  `available: true`. Either one alone is not that claim.
- **`compliance_rules.verified`** — only verified rules can make a product
  non-compliant. While this is `0`, nothing can be found non-compliant.
- **`compliance_rules.applicability_conditions`** — `0` alongside a healthy
  `active_total` means `load_rules` was run and `load_legal_framework` was not.
  That state is worse than an empty rule set because it does not look like one:
  findings come back with no clause and no source citation, and a clause gated
  on a fact nobody stated has no gate to check, so it is evaluated anyway and
  can record a violation the correctly loaded database would have sent to
  review. See the setup sequence in README.md.

The endpoint reports *whether* each dependency answered, never *why* it did
not. Error detail is logged server-side; the response says only `unavailable`,
so it stays useful to the team without being useful to a scanner.

**This is the deployment health-check path.** `railway.json` points
`healthcheckPath` at it, and `SECURE_REDIRECT_EXEMPT` in `config/settings.py`
exempts this one path from the HTTPS redirect so a platform probe arriving over
plain HTTP on an internal network is answered rather than sent a 301. Every
other path still redirects. See [deployment.md](deployment.md).

### `POST /api/v1/images/`

Upload the photographs of a package; receive the finished compliance result.

Runs the whole flow inline - validate, store, OCR, extract, normalise,
evaluate - and returns **201** with the complete `ComplianceCheck`. Extraction
measures at a ~2.2 s median per photograph on the configured Tesseract pipeline
(docs/evaluation-results.md), so there is nothing to poll. When that becomes
slow enough to need a queue, `run_extraction` moves behind it and this response
gains a `pending` shape additively.

`multipart/form-data`:

| Field | Required | Notes |
|---|---|---|
| `image` | yes | A photograph. Validated by `apps.images.validators` in full. **Repeatable** - see [Several photographs, one inspection](#several-photographs-one-inspection). At most 6. |
| `view_type` | no | A `ProductImage.ViewType` value, one per `image` part, positionally. Defaults to `unspecified`. |
| `category_code` | no | A `ProductCategory.code`. Determines which rules apply. An unknown code is a 400, never silently ignored - dropping it would produce a "category not known" result indistinguishable from omitting it. |

**201** carries the verdict (`result`), the engine's plain-language
explanation (`summary`), every declaration that was read with its normalised
value and bounding box, and the two finding lists described under
[Findings and violations](#findings-and-violations) below.
`extraction.is_placeholder` says whether any real recognition happened;
`product_category_code` is `null` when the commodity was not known. `images`
lists every photograph the result was made from.

**201 even when nothing could be read.** An unreadable photograph still
produces a stored, retrievable result whose verdict is `review_required` and
whose summary explains why. That is an outcome, not a failed request.

**400** for a missing file, a file the validators reject, more than 6 files, an
unknown `category_code` or an unknown `view_type`.

### Several photographs, one inspection

A packaged commodity declares different things on different panels - the net
quantity on the back, the retail sale price on a side, a batch number in small
print. A caller may therefore send several photographs of the same package, by
**repeating the `image` part**:

```
POST /api/v1/extraction/
Content-Type: multipart/form-data; boundary=…

--…
Content-Disposition: form-data; name="image"; filename="front.jpg"
…
--…
Content-Disposition: form-data; name="image"; filename="back.jpg"
…
--…
Content-Disposition: form-data; name="view_type"

front
--…
Content-Disposition: form-data; name="view_type"

back
--…--
```

The same applies to `POST /api/v1/images/`. Both first-party clients send this
shape: the web scan page (`frontend/src/services/extractionService.js`,
`buildUploadFormData`) and the mobile app (`mobile/src/api/extraction.ts`).

**They become one inspection, not several.** One `ProductImage` per
photograph, then **one** `ExtractionRun` over all of them, and - on
`/images/` - **one** `ComplianceCheck`. That is the point of the feature
rather than an implementation detail: the rule engine judges the *package*,
and a run per photograph would report the front panel as failing to declare a
net quantity that is printed on the back.

Rules a client can rely on:

- **The order is kept.** The first `image` part is position 1 and becomes
  `ExtractionRun.image`, the primary photograph. The positions are what the
  response's `images[].position` reports and what an interface shows a person
  ("Evidence · Image 2").
- **`view_type` is positional and never repeated.** The *n*th `view_type` part
  describes the *n*th `image` part; a shorter list leaves the rest
  `unspecified`. Stating that the first photograph is the front says nothing
  about the second, so the value is not copied across.
- **A single `image` part behaves exactly as it always has.** One photograph is
  a set of one. A client written before this existed needs no change, and its
  requests take the same path rather than a special case.
- **At most 6 photographs** (`apps.images.constants.MAX_IMAGES_PER_INSPECTION`).
  Every photograph costs a full pipeline pass inside the same synchronous
  request. More than 6 is a **400** on `details.image`.
- **A rejected photograph rejects the whole request.** A set is one inspection,
  and reporting a partial success would leave the submitter believing a panel
  was checked when it was not. The photographs stored before the rejected one
  was reached are orphan rows that nothing points at; no run and no result
  exist.
- **One unreadable photograph does not fail the inspection.** Two good panels
  and a blurred close-up produce a `completed` run: the label was read well
  enough to judge against. The close-up's own entry in `images[]` carries
  `status: "failed"` and its `error_code`, so a submitter can still be told
  which photograph contributed nothing. Only when *every* photograph failed is
  the run itself `failed`.
- **The same photograph twice is refused.** Its declarations would be read and
  counted twice.

#### Which photograph a reading came from

`ExtractedLabelField.image_id` names the photograph each declaration was read
from, and matches one of the `images[].image.id` values in the same response.
`ComplianceEvidence.image_id` does the same for the evidence behind a
violation.

Two things a client must not do with them:

1. **`null` is "not recorded", never "no photograph".** Every reading made
   before this existed has a null here, and so does one whose image row has
   since been deleted. The honest rendering is to say nothing about which
   image.
2. **Evidence for an *absence* falls back to the primary photograph.** There is
   no reading to have a source, and the declaration was absent from the whole
   set, so no panel is more its evidence than another. A client must not turn
   that into "image 1 is missing the net quantity" - that is a claim about
   where a declaration should appear on a package, and this system has not made
   it.

`fields_read` may contain the **same `field_key` more than once** when a
declaration is printed on two photographed panels. Every entry is a real
reading with its own image and confidence, and none is the "wrong" one. Which
reading the rule engine judged against is a separate question, answered by the
finding, which links to the exact reading it used - the engine resolves a
duplicate by taking the earliest photograph's reading, in position order
(`apps.rules.checks.base.CheckContext.from_run`).

### `POST /api/v1/extraction/`

Upload the photographs of a package; receive **what was read off them**, and
nothing more.

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
| `image` | yes | A photograph. Validated by `apps.images.validators` in full — the same path as `POST /api/v1/images/`. **Repeatable**; see [Several photographs, one inspection](#several-photographs-one-inspection). At most 6. |
| `view_type` | no | A `ProductImage.ViewType` value, one per `image` part, positionally. Defaults to `unspecified`. |

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
      "bounding_box": {"x": 4, "y": 4, "width": 300, "height": 18},
      "image_id": "…"
    }
  ],
  "images": [
    {
      "position": 1,
      "status": "completed",
      "error_code": "",
      "error_message": "",
      "processing_ms": 2202,
      "image": {"id": "…", "original_filename": "front.jpg", "…": "…"}
    }
  ],
  "unread_declarations": [],
  "product_classification": {
    "category": "packaged-food",
    "subcategory": "health-supplement",
    "confidence": 0.7232,
    "subcategory_confidence": 0.5517,
    "evidence": ["signal: ingredients (typical of packaged-food)", "…"],
    "category_scores": {"packaged-food": 0.7232, "packaged-non-food": 0.2768},
    "subcategory_scores": {"general-food": 0.1715, "health-supplement": 0.5517, "…": 0.0},
    "classifier_name": "tfidf-logreg",
    "classifier_version": "0.1.0"
  },
  "image": {"id": "…", "image_format": "png", "width": 1024, "height": 768, "…": "…"}
}
```

The body has no `result`, `summary` or `violations` key and must never grow
one. A test asserts their absence.

Five fields are load-bearing and a client should not ignore any of them:

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
- **`product_classification`** — what kind of product the recognised text
  *looks like*, from the pipeline's product classifier: a `category` that is
  a `ProductCategory` code (`packaged-food`, `packaged-non-food`) or
  `"unknown"`, an optional narrower `subcategory`, the classifier's
  `confidence` in that category (or `null` when it attempted no prediction),
  every category's score, and the `evidence` it drew on. **`null` means no
  classification was made** — an older run, a pipeline without a classifier
  (`tesseract` 0.3.0 and earlier, `null-engine`), or a classifier that
  failed; `"unknown"` means the classifier ran and declined. Added in
  `tesseract` 0.4.0. It is an observation about the label, not a decision:
  nothing in the rule engine reads it, and its confidence is **not** a
  compliance figure. A client may offer it as a *suggestion* for
  `category_code`; it must not fill that field without a person confirming.
  See [`ml/product-classification.md`](ml/product-classification.md).

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
| `applicability_declarations` | no | Facts about the package, as `{condition_code: "yes"｜"no"｜"unknown"}`. See below. |

**There is no rule, check-type, severity, engine or threshold parameter, and
there must never be one.** Applicability is answered by
`engine.applicable_rules` from the loaded rule set and the commodity's category
alone. A verdict a client could steer by choosing its own rules would be worth
nothing.

#### `applicability_declarations`

Several clauses of the Rules apply, or do not apply, on facts **no photograph
can establish** — whether the package contains bidi, whether it is imported,
whether it is a domestic LPG cylinder under the Administrative Price Mechanism.
Without them the engine cannot reach a verdict on those clauses, and correctly
returns `review_required` for each rather than guessing. This field is how a
caller states them.

```json
{
  "extraction_run_id": "…",
  "category_code": "packaged-food",
  "applicability_declarations": {
    "imported-product": "no",
    "bidi": "no",
    "domestic-lpg-cylinder": "no"
  }
}
```

**This is not a way to choose which rules run**, and the distinction is what
makes it safe to accept. A declaration states a fact about the goods; what the
Rules make of that fact is still decided by
`apps.compliance.services.applicability` from conditions loaded out of the
verified legal framework. Every answer is recorded against the product with
`source: "submitter"` and surfaces in the `applicability_note` of every finding
it influenced, so a reviewer can see who said what.

Condition codes are `ApplicabilityCondition.code` values, loaded from
`rules/framework/applicability_conditions.json` by
`manage.py load_legal_framework`. **Do not hardcode them in a client** — ask
`GET /api/v1/compliance/applicability-conditions/` (documented below), which
serves exactly the codes that would change an outcome in the installation the
client is talking to. A list copied into a client goes stale the moment a
clause is transcribed or a rule is deactivated, and nothing fails when it
does.

Rules that hold, and the 400s they produce:

- **Omitting the field changes nothing.** An unstated fact stays unestablished,
  which is the behaviour every existing caller already relies on. Sending
  `"unknown"` is the same as not sending the code, and is accepted so a form
  can record that somebody was asked.
- **An unknown condition code is a 400**, not a silent drop — dropping it would
  produce a result reading "this could not be determined", indistinguishable
  from not having sent the fact.
- **A condition the framework records as _not determinable_ is a 400** even
  though it is a real condition. The resolver answers `UNKNOWN` for those
  whatever anyone states — that is what stops a submitter switching off a check
  by asserting a rule 33 relaxation nobody can confirm — so accepting the
  answer would let a caller believe they had declared something.
- **Declarations with no product and no `category_code` are a 400.** They hang
  off the product, and without a commodity no rule applies for them to affect.
- Re-declaring a condition **corrects** the earlier answer rather than adding a
  second row.

**Not available on `POST /api/v1/images/`.** The one-shot upload path takes no
declarations, so a submission made that way reaches `review_required` on the
conditional clauses. Use the two-step path when the facts matter.

**201** with the same `ComplianceCheck` body `POST /api/v1/images/` returns.
201 rather than 200 because an evaluation is a new record: evaluating the same
run twice creates two checks, which is how a result from before a rule was
loaded stays comparable with one from after.

**201 even when no conclusion could be drawn.** An unreadable reading, an
unknown commodity category, or no loaded rules each produce a stored result
whose verdict is `review_required` and whose summary says which of those it
was.

**400** for a missing, malformed or unknown `extraction_run_id`, an unknown
`category_code`, or an `applicability_declarations` entry naming a condition
the framework does not define or cannot use. A run the caller may not use is
the same 400 as an unknown one: a signed-in caller may evaluate only runs whose
photographs they uploaded, an anonymous demonstration caller only anonymously
uploaded runs. See [security.md](security.md#who-may-evaluate-a-stored-reading--post-apiv1compliance).

### `GET /api/v1/compliance/applicability-conditions/`

The facts a submitter may state that would change what this installation
concludes. The discovery half of the POST above: it answers "which questions
are worth asking about this package?"

**Short by construction, and the filters are the contract.** Three of them, and
each removes questions a submitter must not be asked:

1. **Only conditions bearing on something this installation evaluates** — a
   scope gate the engine consults for every check (rules 3 and 26), or a clause
   with an **active** executable rule behind it.
2. **Only `user_declared` conditions.** A `product_category` condition is
   already answered by `category_code`; a `database` one needs a register
   nobody holds; a `not_determinable` one is answered UNKNOWN by the resolver
   whatever anybody states — which is the safeguard that stops a submitter
   switching off a check by asserting, say, a rule 33 relaxation.
3. **Only active rows**, on the condition and on the requirement.

Against the shipped framework this is **17 conditions**, not the 39 the
framework defines.

The POST is deliberately *more* permissive than this list: it accepts any
determinable condition, so a reviewer correcting a miscategorised submission can
still state `food-article` directly. This endpoint describes what a submission
**form** should ask.

```json
{
  "conditions": [
    {
      "code": "bidi",
      "name": "Package containing bidi",
      "description": "…",
      "determination": "user_declared",
      "determination_note": "…",
      "scope": "clause",
      "answers": ["yes", "no", "unknown"],
      "affects": [
        {
          "clause": "6(1)(e)",
          "mode": "exempts",
          "mode_display": "Does not apply to",
          "note": "Proviso (C)(i): no declaration as to retail sale price…",
          "rule_codes": ["LM-PC-0005", "LM-PC-0012"]
        }
      ]
    }
  ],
  "answer_semantics": { "yes": "…", "no": "…", "unknown": "…" },
  "framework_loaded": true
}
```

| Field | Meaning |
|---|---|
| `scope` | `rules_scope` — answering "yes" takes the package out of the Rules or out of Chapter II and **nothing** is checked. `clause` — it excuses or triggers one clause; the rest of the check stands. |
| `answers` | The permitted values, served rather than assumed so a client's radio group is built from the API's vocabulary. |
| `affects[].note` | The framework's own note on the link — the proviso in its own terms. Not composed by the API from the mode and the clause number, and not to be composed by a client either. |
| `affects[].rule_codes` | The executable rules an answer would affect. Empty for a scope gate, which affects every rule. |
| `answer_semantics` | What each answer means, in particular that `unknown` is never read as `no`. Served so a client does not write its own, eventually wrong, explanation. |
| `framework_loaded` | `false` with an empty list means the legal framework was never loaded — a deployment fault, not "nothing is declarable". |

**Never paginated, never filtered.** It is a small fixed vocabulary.

Permissions are the analysis endpoints' — `IsAuthenticatedOrDemoPublic`.
Nothing here is user data: it is the loaded legal framework, the same content
that ships in `rules/framework/` in the repository.

**200** always, including with an empty list.

### `GET /api/v1/compliance/`

The compliance results already stored, newest first. The history behind the two
endpoints above: what has been checked, when, and what came out.

This is the list an inspections/history screen draws, and each row's `id` is the
link to the full result. It is **additive** — `POST` to the same path is
unchanged.

**Paginated**, per the [Pagination](#pagination) section: `?page=`, `?page_size=`
(default 20, capped at 100), and the standard `count` / `next` / `previous` /
`results` envelope.

**Ordering is `created_at` descending, with the check's `id` as tie-breaker.**
Fixed, not a query parameter. The tie-breaker is not decoration: `created_at` is
not unique — two evaluations in the same transaction, a seeded demonstration, or
simply a coarse system clock produce equal timestamps — and an unstable sort
under pagination hides rows. `id` is a random UUID, so as a tie-break it is
arbitrary but *fixed*, which is the property pagination needs.

**No filters.** Not `result`, not a date range, not search. The repository has no
filtering convention and no filter backend installed, and this endpoint does not
invent one ahead of a client that needs it. Adding a filter later is additive
under the versioning rules at the top of this page, and the indexes it would use
(`check_result_idx`, and `created_at`) already exist.

Each row carries **only** what a history list shows or navigates by:

| Field | Meaning |
|---|---|
| `id` | The check's UUID. The link to `GET /api/v1/compliance/<uuid>/`. |
| `status` | Lifecycle of the *evaluation*: `pending` / `running` / `completed` / `failed`. |
| `result` | The **verdict**: `compliant` / `partially_compliant` / `non_compliant` / `review_required`. |
| `result_display` | The verdict's human label, from the model's own choices. |
| `created_at` | When the evaluation was recorded. The sort key. ISO 8601, UTC. |
| `completed_at` | When it finished, or `null`. |
| `engine_version` | Which engine version produced it, so old and new results stay comparable. |
| `extraction_run_id` | The reading it was drawn from. |
| `product_category_code` | Whose rules were considered, or `null` when the commodity was not known. |
| `findings_count` | How many rules were examined. |
| `rules_not_applicable` | How many rules were ruled out as not governing this package. **Not passes.** |
| `violations_count` | How many the package was found to fail. |

`status` and `result` are two different questions and stay separate: `status`
says whether the evaluation ran, `result` says what it concluded. A row whose
status is `failed` has no verdict to show, and a client that collapses the two
invents one.

The two counts are computed **in the database**, and they count the rows the
detail endpoint would actually return — not the stored `rules_*` columns. For a
check written before findings were recorded, those differ, and the row count is
the honest number.

**Not included, deliberately:** `summary`, `findings`, `violations`, evidence
excerpts, bounding boxes, confidences, the reading, and image metadata. A page of
twenty results would otherwise carry a few hundred kilobytes of evidence a list
cannot display. All of it is on the detail endpoint below, which remains the
single source of the full trace.

**Empty history is `200` with `count: 0` and `results: []`**, never a 404.
"Nothing has been evaluated yet" is a state the screen must be able to draw.

> **Results are scoped to the caller.** An authenticated caller lists the
> checks **they** requested and no others; `requested_by` is recorded on every
> check and is now filtered on. An anonymous caller — only possible with
> `DEMO_PUBLIC_ANALYSIS_API` on — lists the checks that were requested
> anonymously.
>
> `GET /api/v1/compliance/<uuid>/` applies the same rule, so an id obtained
> anywhere does not read a result the caller does not own. A result belonging to
> somebody else is **404**, byte-identical to one that does not exist: a 403
> would confirm that the id names a real submission.
>
> **What remains open:** anonymous checks are a *shared pool*. Two people using
> the same demonstration deployment see each other's uploads, because an
> anonymous caller has no identity to scope to. Closing that needs an owner for
> a check with no user — a session binding, a signed link — and belongs with the
> authentication work. `DEMO_PUBLIC_ANALYSIS_API` defaults to `False`, so a
> deployment holding real submissions has no anonymous pool unless it is opened
> on purpose.

### The compliance result body

Returned by `POST /api/v1/compliance/`, `POST /api/v1/images/` and
`GET /api/v1/compliance/<uuid>/` alike.

**Three kinds of evidence come back, and a client must keep them apart.**
Collapsing any two of them is the most damaging thing a UI can do with this
response:

| Key | What it is |
|---|---|
| `extraction` | What the pipeline **read** off the photograph — with a confidence and a bounding box per declaration. An observation. Its `product_classification` sub-key is a second observation — what kind of product the text *looks like* — and is likewise never a conclusion; see `POST /api/v1/extraction/` above. |
| `applicability_declarations` | What a person **asserted** about the goods. No photograph could establish these, and nothing verified them. |
| `findings` | What the rules **concluded** from both. See *Findings and violations* below for the per-finding fields. |

**One result, however many photographs.** `images[]` lists every photograph the
inspection was made from, in position order, and `image` is the primary one
(`images[0].image`) kept for clients that predate the set. There is one verdict,
one summary and one set of findings whatever the length of that list: the rule
engine evaluated one reading, assembled from every panel. A client showing a
verdict per photograph would be describing an analysis this system did not
perform. Say "3 images checked" and show one result.

Each entry is `{position, status, error_code, error_message, processing_ms,
image}`. `status` there is that **one photograph's** outcome and is not the
run's: a run may be `completed` - the label was read well enough to judge
against - while one of its photographs is `failed` because it was too blurred
to contribute. Both are true, and an interface that showed only the first
would leave a submitter unable to see which photograph to retake.

#### Counts

`rules_evaluated` = `rules_passed` + `rules_failed` + `rules_inconclusive`.

`rules_not_applicable` is **outside** that sum, deliberately. A rule that did
not govern the package examined nothing, so it is not a pass; adding it to
`rules_passed` would turn a set of carve-outs into a clean bill of health.

#### `applicability_declarations[]`

The facts stated about this package, so a permalinked result can show *why* a
clause was excused rather than only that it was.

| Field | Notes |
|---|---|
| `code`, `name` | The condition, from the legal framework. |
| `answer`, `answer_display` | `yes` / `no` / `unknown`. |
| `source`, `source_display` | Who stated it. Never "read off the label" — using an extracted value to decide whether to check for it would be circular. |
| `note` | Free text recorded with the answer. |
| `stated_before_this_check` | Declarations hang off the **product**, not the check, so a fact recorded *after* an evaluation still appears here. `false` marks one that could not have influenced this result. `null` when the check recorded no start time to compare against. |

Empty is the ordinary case, and it means something: nothing was stated, so any
clause whose applicability turns on such a fact was reported as undetermined
rather than decided either way.

#### `product_category_source` and `applicability_assessment`

Additive, on the same three bodies. Together they answer "who chose the rule
set, and what did the label classifier have to do with it?" — see
[automatic-applicability.md](automatic-applicability.md).

| Field | Notes |
|---|---|
| `product_category_source` | `submitter`, `reviewer` or `classifier`; `null` when there is no category. `classifier` means the deployment's accepted policy (`AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS`) established the category from the label classification without a person — the rules that ran were chosen by a model, and every client must say so. |
| `applicability_assessment.status` | The **policy's** verdict on the classification, not a compliance state: `confident` (accepted, category established automatically), `uncertain` (a suggestion for a person), `unknown` (the classifier declined), `failed` (none recorded, null, or malformed). |
| `.reason` | Why, in plain words. |
| `.classifier` | `name`, `version`, `confidence` (the model's own, about the product type — never a compliance figure), `evidence[]`. |
| `.policy` | `accepted`, `min_confidence`, `evaluation` — the entry that licensed this artifact, or `false` / `null`. |
| `.category` | `proposed`, `proposed_name`, `confidence`, `in_effect`, `in_effect_source`, `disposition` (`established_automatically`, `confirmed_by_submitter`, `stated_by_submitter`, `contradicted_by_submitter`, `needs_confirmation`, `not_proposed`), `reason`. |
| `.facts[]` | Conditions a subcategory suggested — `condition`, `name`, `proposed_answer`, `confidence`, `basis`, `affects[]` (`"6(1)(d): exempts"`), `in_effect` (`yes`/`no`/`unknown`, from the declaration rows), `in_effect_source`, `disposition`, `reason`. **Never recorded from the classifier**; `in_effect` changes only when a person declares. |
| `.questions[]` | What a person still has to answer, and nothing else: `kind` (`category` / `condition`), `code`, `suggested`, `prompt`, `outcome` (what answering does — which requirements it selects, that the same stored reading is re-checked rather than the photograph read again, and that the answer is recorded as the person's), `choices[]` (`{code, name}` for a category question — the active categories, so a client need not hardcode them). Empty means nothing is open. |
| `.evidence` | The reading behind the suggestion. `label_signals[]` — `{phrase, indicative_of, snippet}` — are phrases **this run's reading contains**, each with the surrounding words so it can be checked against the photograph; `indicative_of` is what such a phrase is *typically* found on, never a claim about this package. `declared_fields[]` — `{field_key, value}` — are the declarations the extractor read, as context. `model_terms[]` are n-grams the model weighed: **internals**, for a technical disclosure, not statements about the product. `has_supporting_evidence` is false when the first two are empty, and `note` then says which case it was — a client must show it rather than an empty space. Nothing here is generated. |

A confirmation is sent through the existing request fields — `category_code`
for the type, `applicability_declarations` for a fact — and the response then
reports `confirmed_by_submitter`. The classifier's suggestion is never sent by a
client on its own behalf. One relaxation on the request: `applicability_declarations`
without `category_code` is accepted when the policy will establish a category
for the run; under the default (empty) policy the request is refused as before.

#### There is no compliance score

**No percentage, no grade, no aggregate confidence exists in this API, and none
may be derived from it in a client.** A number would imply that partial
compliance with a labelling requirement is partial credit, which is not how the
Rules work. The per-reading `extracted_confidence` is the OCR engine's opinion
of its own characters and affects no outcome; it is not a compliance figure and
must not be aggregated into one. The same applies to
`extraction.product_classification.confidence`: it is a classifier's opinion
of what kind of product the label is, it affects no outcome, and it is not a
compliance figure either.

### `GET /api/v1/compliance/<uuid>/`

The same body as `POST /api/v1/compliance/`, for a result already computed.
Exists so a result survives a page reload and can be sent to a reviewer as a
link. The id is a UUID so holding one result's link does not let you walk to
another's by subtracting one.

This is the **complete trace**, and the list endpoint above deliberately is not:
`summary`, `findings`, `violations`, evidence, bounding boxes, confidences and
the reading are all here and only here. A client lists with
`GET /api/v1/compliance/` and fetches this for the one result the user opened.
The same not-scoped-to-a-user limitation noted above applies here too.

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
| `clause` | The sub-rule this concerns, as the Rules number it — `6(1)(c)`. Empty when the rule is not mapped to the legal framework. |
| `legal_source_citation` | The instrument that established the clause as evaluated — `G.S.R. 629(E)`. Snapshotted, so it stays legible after a later amendment supersedes it. |
| `check_type` | Which registered deterministic check asked the question. |
| `detection_method` | What kind of evidence could settle this requirement **at all**. See below. |
| `field_key` | Which declaration it concerns. |
| `status` | `passed` / `failed` / `inconclusive`. |
| `message` | What was observed and why, in plain language. |
| `evidence_excerpt`, `bounding_box` | What was read, and where on the image. |
| `extracted_raw_value` | The declaration exactly as recognised, before normalisation. |
| `extracted_normalized_value` | The normalised interpretation of it, or `null` when no normaliser ran. |
| `extracted_confidence` | How sure the OCR/ML layer was about the reading behind this finding. |
| `applicability_note` | Why the rule was applied, and what about its applicability could **not** be established. |
| `severity` | Triage ranking only. It carries **no legal weight** — `rules/SCHEMA.md` says so, and the UI must not present it as one. |
| `downgraded_from_failed` | The check failed, but the rule is not verified against the authoritative legal text, so the engine recorded it as inconclusive rather than as a violation. |
| `details` | Validator diagnostics. Shape is validator-specific. |
| `violation` | Id of the violation this became, or `null`. |

A finding carries no image of its own. Which photograph its evidence came from
is on the **violation** it became — `violations[].evidence[].image_id` — and on
the reading it drew on, `extraction.fields_read[].image_id`. A finding that
became no violation (a pass, an inconclusive outcome, a downgraded failure) has
no evidence row and therefore no image, and a client must show none rather than
fall back to the first photograph. See
[Which photograph a reading came from](#which-photograph-a-reading-came-from).

Five of these are easy to misread:

- **`inconclusive` is not a soft fail.** It means the check could not be
  decided — usually because the photograph was not readable, or because a fact
  deciding whether the rule applies was never declared. Treating it as either a
  pass or a violation is the most damaging thing a client can do with this data
  — it is the difference between "your package is illegal" and "we could not
  read your photo".
- **`not_applicable` is not a pass either.** The rule does not govern this
  package: it was exempted under rule 26, taken out of scope by rule 3, or
  binds only packages of a kind this one is not. Nothing about its declarations
  was examined, so counting it as a pass turns a set of exemptions into a clean
  bill of health. `applicability_note` says which condition ruled it out.
- **`extracted_confidence` is recorded, not enforced.** No rule in this
  repository conditions its outcome on it, so a `passed` finding built on a
  low-confidence reading is still `passed`. The number is exposed precisely so
  that cannot happen silently: a client showing a finding should show what the
  reading behind it was worth. `null` means the OCR engine did not report a
  confidence, and is **not** zero.
- **`downgraded_from_failed` is a legal safeguard firing**, not a data problem.
  An unverified rule can flag a package for human review; it can never tell a
  user their package breaks the law.
- **`detection_method` says whether a photograph could ever have settled
  this.** Values other than `ocr`, `cv` and `ocr_cv` name evidence this
  pipeline does not have — a physical weighing, a regulator's register, an
  e-commerce listing — and a finding carrying one of those is a prompt for
  human review whatever its `status` reads. No such rule is currently active,
  but the field is part of the contract so that adding one cannot silently
  present an unanswerable question as an answer.
- **`applicability_note` is not boilerplate.** It carries the caveat that
  applies to **every** result, including passing ones: applicability is decided
  from the commodity category alone, and the facts rule 3 and rule 26 turn on —
  net quantity as a trusted value, buyer type, commodity class — are not
  collected. So a rule may have been applied to a package that is outside the
  Rules entirely, and any relaxation granted under rule 33 is invisible here. A
  client that hides this field is presenting a narrower claim than the data
  supports.

`extracted_raw_value` and `extracted_normalized_value` are both present and
neither replaces the other. The raw text is what was recognised; the normalised
value is an interpretation of it, and is `null` when no normaliser exists for
that declaration — never because the reading was empty. Show the raw value
where a reviewer needs to check the interpretation.

### `GET /api/v1/rules/`

The executable rules this installation has loaded (`ComplianceRule` rows), active
and inactive. It answers "which rules does this server hold, and which does it
evaluate?" — for a screen that names the rules.

**It is an inventory, not a compliance decision.** Nothing here says whether any
package complies, or which rules would apply to one. That is decided per package
by the compliance engine and returned by `POST /api/v1/compliance/` and
`GET /api/v1/compliance/<uuid>/`. No legal requirement is evaluated or restated
by this endpoint.

**Source of truth.** The rows are what the server's database holds: authored in
`rules/definitions/`, loaded by `manage.py load_rules`, and linked to clauses by
`manage.py load_legal_framework`. A client should display these rather than a
copy of the repository files, because a server that has not run `load_rules`,
or has a rule switched off, differs from those files, and only this response
reflects that.

Paginated with the shared [Pagination](#pagination) class: `page`, `page_size`
(default 20, capped at 100), and the standard four-key envelope. Ordered by
`code`, which is unique, so the order is total. As shipped, all 12 rules fit on
the default page.

```json
{
  "count": 12,
  "next": null,
  "previous": null,
  "results": [
    {
      "code": "LM-PC-0002",
      "title": "Common or generic name of the commodity",
      "legal_reference": "Rule 6(1)(b) of the Legal Metrology (Packaged Commodities) Rules, 2011",
      "clause": "6(1)(b)",
      "source_status": "verified",
      "is_active": false,
      "effective_from": "2011-04-01",
      "effective_to": null
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `code` | The stable identifier a finding cites (`rule_code` on a finding). Never reused. |
| `title` | The rule's own name for the requirement, as loaded. |
| `legal_reference` | The provision as the source numbers it. `""` when not established. It is never guessed and never `null`. |
| `clause` | The clause of the Rules this rule evaluates, from its linked `RuleRequirement`. This is the same link the engine snapshots onto every finding. **`null` when the rule is not linked to a clause**, e.g. on a database where `load_legal_framework` has not been run. It is never derived from `legal_reference`. |
| `source_status` | `verified` or `unverified`. Only a verified rule can report a package as non-compliant; an unverified one can at most send it to review. |
| `is_active` | Whether the engine considers the rule at all. **`false` rows are listed**, not hidden: LM-PC-0002 ships inactive, and a rule that is recorded but not evaluated is the more important of the two facts to be able to find. `true` means the flag and nothing more. Whether an active rule runs for a given package also depends on its effective window and the package's category, which the engine decides per check. |
| `effective_from`, `effective_to` | The rule's effective window as ISO dates, or `null`. `effective_to: null` means no end date is recorded. |

**Deliberately not in the response:**
- `check_type` and `parameters`: validator configuration, including values a
  client could mistake for legal thresholds.
- `applies_to_categories` and `requires_applicability_conditions`: how
  applicability is decided.
- `source_note`: who verified the rule.
- `requirement` and `severity`: not part of this contract.

A client that had the first two could re-implement a check. The compliance engine
is the only thing that applies them.

**Read-only.** GET, HEAD and OPTIONS only; POST, PUT, PATCH and DELETE are
**405** `method_not_allowed`. Rules change by editing `rules/definitions/` and
reloading, never over the API. There is no detail route: `code` identifies a
rule within the list.

**Permissions** are those of `GET /api/v1/compliance/applicability-conditions/`,
the other endpoint serving loaded legal-framework metadata:
`IsAuthenticatedOrDemoPublic`. An authenticated caller may read it; an
anonymous caller may read it only while `DEMO_PUBLIC_ANALYSIS_API` is on, and
gets **403** otherwise. It is not unconditionally public, because
`/api/v1/health/` remains the only such endpoint. It holds no user data: every
caller who may reach it sees the same rows, and no submission, image, reading or
result appears in it. Anonymous reads are throttled like any other.

**200** always for an allowed GET, including `count: 0` with an empty `results`
list on a server where no rules are loaded. Compare `compliance_rules` on
`GET /api/v1/health/`: its `active_total` is the number of rows here with
`is_active: true`.

### Which endpoints the frontend actually calls

Recorded here because the choice is not obvious from the endpoint list, and
because a second client should make the same one.

The scan screen uses the **two-step path**, not the one-shot one:

```
GET  /api/v1/compliance/applicability-conditions/   (once, on mount)
POST /api/v1/extraction/   ->  ExtractionRun id
POST /api/v1/compliance/   ->  ComplianceCheck   (that id, no re-upload)
```

The catalogue is fetched once when the screen mounts, and its failure is **not**
fatal to the flow: the declarations are optional, and without them the engine
reports REVIEW REQUIRED on the clauses that turn on an undeclared fact, which is
a correct result rather than a broken one.

`POST /api/v1/compliance/` is repeatable against the same run id, and the scan
screen offers exactly that after a verdict: state a fact, re-evaluate the
**same stored reading**. The photograph is neither uploaded nor read again, so
the reading on screen cannot change underneath the new verdict. Each call does
create a new `ComplianceCheck` row, which is intended — a result from before a
fact was stated stays comparable with the one from after.

It needs the reading on screen next to the verdict, so that a reviewer can
check a finding against the text it was drawn from. `POST /api/v1/images/`
returns both in one response and remains supported - `analyseImage` in
`frontend/src/services/complianceService.js` still calls it - but a client that
displays the reading should evaluate the stored run rather than upload twice.

`GET /api/v1/compliance/<uuid>/` backs the frontend route `/result/<uuid>`,
which is what makes a result reloadable and sendable as a link.

`GET /api/v1/compliance/` backs the frontend route `/inspections`, which lists
the stored assessments and links each row to `/result/<uuid>` for the full
trace. The screen follows the `next` / `previous` URLs in the envelope rather
than building `?page=` itself, and offers no filter, sort or search, because
this endpoint has none to offer.

One consequence of the response shape is worth stating, because it looks like a
gap and is not: **`ProductImageSerializer` exposes no URL, and no endpoint
serves the stored bytes back.** The frontend therefore draws its evidence
overlay over the `File` the user selected, using `image.width` / `image.height`
as the coordinate space that `bounding_box` is expressed in. A result opened
from a link shows the findings and their excerpts, and says the photograph is
not available on that device rather than showing an empty frame.

### Permissions on the six analysis endpoints

All six — upload-and-analyse, upload-and-extract, evaluate-a-reading, reading a
stored result back, listing stored results, and listing the declarable
applicability conditions — follow the deny-by-default rule and require an
authenticated user, unless
`DEMO_PUBLIC_ANALYSIS_API` is set. That setting **defaults to False** and is
intended only for a demonstration, where no login screen exists yet. It affects
these six — five URL routes, since the collection's GET and POST share one —
plus one read-only route that is not an analysis endpoint: `GET /api/v1/rules/`,
the loaded rule list, which holds no user data and follows the same rule. It
affects nothing else, and uploads still go through validation and anonymous
throttling either way. The set is pinned by
`apps/core/tests/test_demo_mode_scope.py`; see
[docs/deployment.md](deployment.md#demonstration-mode) for what turning it on
makes true.

**The permission class does not do authorisation.** It answers "may this caller
reach the analysis API?", never "is this result theirs?". The second question is
answered separately, by `CallerScopedCheckQuerysetMixin` in
`apps/compliance/api/views.py`, which scopes both the history list and the
detail endpoint to the caller — see the note under `GET /api/v1/compliance/` for
what that covers and what it leaves open. Reaching the API and being entitled to
a row are two permissions, and only the first is the permission class's job. See
`apps/core/api/permissions.py` (re-exported from
`apps/compliance/api/permissions.py`, which is where it used to live).

## Planned endpoints

Not implemented. Listed so branches do not invent conflicting shapes — agree
the contract here in a PR before building it.

| Endpoint | Branch |
|---|---|
| `POST /api/v1/products/` | `feature/product-upload` |

`GET /api/v1/rules/` was listed here for `feature/rule-management` and is now
built. See [its section above](#get-apiv1rules).

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
- Collections are paginated with `DefaultPageNumberPagination` and ordered by a
  sort key **plus a unique tie-breaker**. See [Pagination](#pagination).
- Validation belongs in serializers. Business logic belongs in
  `apps/*/services/`, never in a view.
- Never return a partially-built object with fabricated fields to make a
  response look complete. Omit what is not known, or return `null`.
