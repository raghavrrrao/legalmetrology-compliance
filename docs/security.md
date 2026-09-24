# Security notes

Baseline security for the base structure, and the reasoning behind each choice.
This is a foundation, not a hardened deployment — see "Known gaps" at the end.

## Secrets

Nothing secret is in this repository. Verified: the only credential-shaped
strings in tracked files are the literal `replace-me-...` placeholders in
`.env.example`.

| Rule | Where enforced |
|---|---|
| `.env` never committed | `.gitignore`, plus `!.env.example` so the template stays tracked |
| No default for `DJANGO_SECRET_KEY` | `settings.py` — a missing key raises at startup rather than falling back to a value identical on every machine |
| No default for database credentials | `settings.py` |
| Frontend variables are public | `frontend/.env.example` carries an explicit warning |

**Vite inlines every `VITE_`-prefixed variable into the browser bundle.**
Anything in `frontend/.env` is readable by anyone who views source. It is
public configuration, not client-side storage of a secret.

If a secret is ever committed: rotate it. Deleting it in a later commit does
nothing — it remains in history and in every clone.

## Image upload

Uploads are the largest attack surface here. An uploaded file is
attacker-controlled in every respect: name, declared content type, size, bytes.

`apps/images/validators.py` applies these in order, each covering something the
others do not:

| Check | Defeats |
|---|---|
| Extension allowlist | Casual wrong-type uploads. Cheap, proves nothing on its own. |
| Content-type allowlist | Same. Both are *claims*. |
| Size limit | Resource exhaustion. Enforced at the app layer as well as by `DATA_UPLOAD_MAX_MEMORY_SIZE`, so a caller building an upload in code cannot bypass it. |
| Pixel-count limit | **Decompression bombs.** A 40 KB PNG can declare dimensions expanding to gigabytes. Dimensions are read from the header and rejected *before* a full decode. |
| Minimum dimension | Images too small to carry legible text. |
| `Image.open()` + `verify()` | **The check that matters.** It asks the decoder what the bytes are, rather than asking the uploader. This is what catches an executable or a script renamed to `.png`. |
| Decoded-format allowlist | A file that decodes as something we do not support, whatever it claimed. |

Allowlists throughout, never denylists. A denylist is a list of the attacks
someone already thought of.

**SVG is deliberately excluded.** It is an XML document that can carry script
and external entity references, not an image in any sense useful for OCR.

### Filename handling

The uploaded filename is **never** used to build a path on disk. Every stored
file gets a generated random name under
`product-images/<YYYY>/<MM>/<uuid><ext>`.

That single decision eliminates path traversal (`../../etc/passwd`), collisions
between two users uploading `photo.jpg`, and Windows reserved device names
(`CON`, `NUL`, `LPT1`) — without trying to enumerate and sanitise each one.

The original name is kept as `original_filename` for display only, after being
stripped of directory components and control characters (which can forge log
lines and corrupt terminal output) and length-capped.

### Storage

Uploaded images are third-party content — trade dress, sometimes incidental
personal data. They are stored outside the static tree, are git-ignored, and
are served by Django **only** when `DEBUG=True`. In a deployment, serving is
the web server's or object store's job, behind access control.

`checksum_sha256` on every image ties a compliance result to the exact bytes
analysed. If a stored file is later replaced or corrupted, the mismatch is
detectable rather than silent.

In the deployed configuration nothing serves media at all: Django serves
`MEDIA_URL` only under `DEBUG=True`, and WhiteNoise is scoped to `STATIC_ROOT`.
A deployed instance returns 404 for `/media/...`, which is the correct default
for third-party content — an endpoint that serves it will have to add access
control at the same time.

Note the availability consequence, which is separate from the privacy one: on a
managed platform the container filesystem is ephemeral, so uploaded photographs
are lost on every deploy unless a volume is mounted. The database keeps the
result rows and loses the evidence they were drawn from. See
[deployment.md](deployment.md).

## Django configuration

Set in `backend/config/settings.py`:

| Setting | Value | Purpose |
|---|---|---|
| `SECURE_CONTENT_TYPE_NOSNIFF` | `True` | Stops MIME sniffing. |
| `X_FRAME_OPTIONS` | `DENY` | Clickjacking. |
| `SECURE_REFERRER_POLICY` | `same-origin` | Limits referrer leakage. |
| `SESSION_COOKIE_HTTPONLY` | `True` | Session cookie unreadable from JS. |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | `not DEBUG` | HTTPS-only outside development, automatically. |
| `SESSION_COOKIE_SAMESITE` / `CSRF_COOKIE_SAMESITE` | `Lax` | CSRF defence in depth. |
| `SECURE_SSL_REDIRECT`, HSTS | enabled when `DEBUG=False` | Transport security in deployment. |
| `SECURE_REDIRECT_EXEMPT` | `["^api/v1/health/$"]` | One path, exempted from the HTTPS redirect. See below. |
| `STORAGES["staticfiles"]` | WhiteNoise manifest storage when `DEBUG=False` | Serves `STATIC_ROOT` only — never `MEDIA_ROOT`. |

Tying the cookie flags to `DEBUG` means a deployment with `DEBUG=False` gets
secure cookies without a second setting anyone could forget.

### The health-check exemption, and its cost

`/api/v1/health/` is the one path the HTTPS redirect does not apply to. This is
a deliberate trade and belongs in a security document rather than only in a
deployment one.

**Why.** A platform health probe reaches the container over plain HTTP on an
internal network and does not follow redirects. With the redirect applied, every
probe receives a 301, the health check never passes, and the deployment is
rolled back — reporting an error that names neither HTTPS nor the health check.

**What it costs.** A plain-HTTP request to that one path is answered instead of
being redirected. The endpoint is already public and returns no configuration,
no credentials, no user data, no OCR text and no image — only whether each
dependency answered. HSTS still applies, so a browser that has seen this host
once will not send it plain HTTP again.

**What it does not cost.** The exemption is one exact path, not a prefix.
`/api/v1/health/extra/` still redirects, and so does every other endpoint. Both
directions are asserted in `backend/apps/core/tests/test_https_redirect.py`, so
the pattern cannot be widened without a test failing.

## API abuse

- Permissions **deny by default**; public endpoints opt in explicitly.
- Throttling: 30/min anonymous, 120/min authenticated, configurable.
- Health is exempt from throttling — a throttled health check reports a false
  outage.

## Authorisation — who may read a stored result

Reaching an endpoint and being entitled to a row are two different permissions.
`IsAuthenticatedOrDemoPublic` answers only the first.

`CallerScopedCheckQuerysetMixin` (`apps/compliance/api/views.py`) answers the
second for `GET /api/v1/compliance/` and `GET /api/v1/compliance/<uuid>/`:

| Caller | Sees |
|---|---|
| Authenticated | The checks where `requested_by` is that user. Nothing else. |
| Anonymous (demo switch on) | The checks requested anonymously — the demonstration pool. |
| Anonymous (demo switch off) | Nothing; the request is refused before this point. |

Somebody else's result returns **404**, with a body identical to a result that
never existed. A 403 would confirm that the id names a real submission, which is
exactly the fact a caller who does not own it must not be able to establish.

Staff get no bypass here. A superuser who needs every row uses the admin site,
which is already the unrestricted path; a second one reachable from any staff
session would be a wider hole than the one it opens for convenience.

Covered by `apps/compliance/tests/test_result_ownership_api.py`, which asserts
the cross-user matrix directly.

### Who may evaluate a stored reading — `POST /api/v1/compliance/`

**Fixed vulnerability.** This endpoint takes an `extraction_run_id` and answers
with a result carrying that run's whole reading. It used to resolve the id with
an unscoped `ExtractionRun.objects.get(pk=...)`, so any caller the permission
class admitted could name another person's run and:

- read their label: the full recognised text, every declaration read, and the
  photographs' metadata, returned inside the result;
- keep that access: the new check was recorded as the caller's own, so it sat
  in their history and could be reopened;
- rewrite the applicability facts stated about the run's product (reachable
  where the photographs are linked to a product, as `POST /api/v1/images/` with
  a `category_code` does), and attach a check of their own to that product.

An anonymous demonstration caller could do the same to a signed-in user's run.

**The rule now enforced** (`apps/compliance/api/ownership.py`, applied while the
request is validated):

| Caller | May evaluate |
|---|---|
| Authenticated | A run whose photographs were **all** uploaded by that user. |
| Anonymous (demo switch on) | A run whose photographs were **all** uploaded anonymously. |
| Anonymous (demo switch off) | Nothing; the request is refused before this point. |

- **Every photograph, not the primary one.** A run reads a set of 1–6
  photographs: `ExtractionRun.image` is position 1 and each is an
  `ExtractionRunImage` row. The rule checks all of them, so a run that mixes
  owners — or owned with anonymous photographs — is usable by no one. The API
  never builds such a run, but the extraction service does not forbid one, and
  checking only `ExtractionRun.image` would hand back readings of photographs
  the caller does not own.
- **A signed-in user does not inherit the anonymous pool**, matching the result
  endpoints above.
- **A refused run is the same 400 as an unknown one** — code
  `validation_error`, the same message, the same field. A distinct "not yours"
  would confirm that the id names a real submission.
- **Nothing is written first.** The check happens during validation, before the
  view creates a product, records a declaration or creates a check, so a refused
  request leaves the database as it found it.

**A UUID is an identifier, not an authorisation.** Random UUIDs make a run hard
to guess, but they are handed out in responses, appear in history rows and are
written to server logs; knowing one must never be enough to use it. Ownership
is read from `ProductImage.uploaded_by`, the only ownership the schema records
for a reading — `ExtractionRun` has no owner column, and adding one is part of
the authentication work below.

**What this does not do.** It does not make anonymous runs private: every
anonymous caller of a demonstration deployment still shares one pool, of
readings as of results, because the API cannot tell one anonymous caller from
another. It does not add private inspection history, device identity or
accounts. Those need an identity mechanism, which is `feature/authentication`'s
decision. And because ownership is a nullable column that is cleared when a
user is deleted (`on_delete=SET_NULL`, on `uploaded_by` as on `requested_by`), a
deleted user's readings and results become indistinguishable from anonymous
ones and fall into that pool; what deleting a user should do to their
inspections is a decision for the same work.

Covered by `apps/compliance/tests/test_run_ownership_api.py`, which reproduces
the attacks through `POST /api/v1/extraction/` and `POST /api/v1/images/` and
checks every refusal against the database as well as the response.

## Logging

Application logs go through the `apps` and `labelextract` loggers.

**Never log** image bytes, full request bodies, credentials, tokens, session
keys, or `SECRET_KEY`. Exceptions are logged with tracebacks server-side; API
responses carry only a stable code and a safe message.

The health endpoint follows this: it reports *whether* the database answered,
never *why* it did not. A connection string in an error response is useful to
an attacker and to nobody else.

## Data privacy — what is actually stored

Described from the schema and the code, not from a policy. Nothing here is a
commitment; it is a statement of current behaviour.

| Stored | Where | Notes |
|---|---|---|
| The uploaded image file | `MEDIA_ROOT/product-images/<YYYY>/<MM>/<uuid><ext>` | The bytes as received. Never re-encoded, never renamed from the client's name. |
| Image metadata | `images.ProductImage` | Sanitised original filename, decoded format, size, dimensions, SHA-256, and `uploaded_by` (null for anonymous). |
| The recognised text | `extraction.ExtractionRun.recognised_text` | **Everything OCR read off the photograph**, in full — including any text on the label that is not a declaration. |
| Engine raw output | `extraction.ExtractionRun.raw_output` | The pipeline's own structure, verbatim. |
| Each read declaration | `extraction.ExtractedLabelField` | Raw value, normalised value, confidence, bounding box. |
| Stated applicability facts | `catalog.ProductApplicabilityDeclaration` | What a submitter asserted about the goods, with its source. |
| The verdict and its trace | `compliance.ComplianceCheck`, `ComplianceFinding`, `ComplianceViolation`, evidence rows | Snapshotted, so a result keeps meaning what it meant. `requested_by` is null for anonymous. |
| User accounts | `accounts.User` | Only if accounts are created. There is no sign-up flow. |

**Retention: indefinite.** Nothing expires, and no scheduled job deletes
anything. A stored image, its reading and its verdicts remain until a person
removes them.

**Deletion: no API for it.** No endpoint deletes an image, a run or a check.
Removal is a database or admin-site operation. `ComplianceCheck.product` and
`ProductImage.product` cascade from `Product`, so deleting a product removes its
images and their analyses; `ComplianceFinding.rule` is PROTECTed, so a rule with
recorded outcomes cannot be deleted out from under a finding.

**Uploaded images are not publicly served.** `MEDIA_URL` is routed by Django
only when `DEBUG=True` (see `config/urls.py`). No serializer returns a file URL:
the API exposes image *metadata*, never a link to the bytes. In a deployment,
serving media is the web server's or object store's job, and access control
there has to be configured deliberately — it is not inherited from this project.

**Who can read stored analysis data:** see *Authorisation* above. The residual
case is the anonymous demonstration pool.

**Logs.** `recognised_text` is never logged. What the `apps` loggers write for an
analysis is the image id, the run status, the verdict and the rule count
(`analysis_service`), and upload rejection *reasons* — never the file, never the
recognised text, never a request body. Unhandled exceptions are logged with
tracebacks server-side and never returned to a client.

**Incidental personal data is realistic here.** A label photograph can capture a
hand, a shelf, a shop; a consumer-care declaration is a real telephone number and
e-mail address, and it is stored as read. That is inherent to the task rather
than a defect, and it is the reason media sits outside the static tree with
`FILE_UPLOAD_PERMISSIONS = 0o640` and no public route.

## Error handling

- Unhandled exceptions return a plain 500. They are never converted into a
  200-with-error-body, which would hide failures from any client checking the
  status code.
- `DEBUG=False` in deployment means Django never renders a traceback.
- Error responses carry a stable `code` and a user-safe `message`. Internal
  detail stays in the logs.

## Known gaps

Deliberately not addressed in the base structure. Listed so nobody assumes they
are covered.

| Gap | Notes |
|---|---|
| **Throttling is per-process** | DRF's counters live in `LocMemCache`, which is per-process, so N workers means N counters and roughly N x the configured rate. Mitigated rather than fixed: `backend/gunicorn.conf.py` runs **one worker** by default, which makes the configured rate the real rate. Raising `WEB_CONCURRENCY` reintroduces the gap and needs a shared cache (Redis/Memcached) first. |
| **No antivirus scanning** | Format validation is not malware scanning. Consider ClamAV if uploads are ever re-served to other users. |
| **No login screen** | Session authentication and deny-by-default permissions exist; there is no sign-in UI, so a demonstration uses `DEMO_PUBLIC_ANALYSIS_API` — anonymous analysis, rate-limited, and never a substitute for authentication on a service holding real submissions. `feature/authentication` owns this. |
| **Anonymous results are a shared pool** | Compliance results *are* scoped to the caller (see above), but an anonymous caller has no identity to scope to, so anonymous checks - and anonymous readings, which any anonymous caller may evaluate - are visible to every anonymous caller of the same deployment. Only reachable with `DEMO_PUBLIC_ANALYSIS_API` on, which defaults to off. |
| **No per-object authorisation on images** | `ProductImage.uploaded_by` is now enforced for one purpose: which readings a caller may evaluate (see *Who may evaluate a stored reading*). No endpoint returns an image or its file today; any endpoint that does must scope by the same column. |
| **Uploaded images are unencrypted at rest** | Filesystem permissions only (`FILE_UPLOAD_PERMISSIONS = 0o640`). |
| **No audit log** | Who viewed which compliance result is not recorded. |
| **No dependency scanning in CI** | `npm audit` reports 0 vulnerabilities at time of writing; nothing runs it automatically. |
| **No security headers beyond Django's** | No CSP. Relevant once the frontend is deployed. |

`feature/security-hardening` owns closing these.

## Before deploying

- [ ] `DJANGO_DEBUG=False`
- [ ] Fresh `DJANGO_SECRET_KEY`, not reused from any developer machine
- [ ] `DJANGO_ALLOWED_HOSTS` set to real hostnames
- [ ] `CORS_ALLOWED_ORIGINS` set to the real frontend origin only
- [ ] `DJANGO_MEDIA_ROOT` outside the repository, not web-served directly
- [ ] Database user is not a superuser
- [ ] HTTPS terminated in front of Django
- [ ] Throttling backed by a shared cache **or** a single worker (the default)
- [ ] `DEMO_PUBLIC_ANALYSIS_API=False` on any deployment holding real submissions
- [ ] Per-object authorisation reviewed on every endpoint returning user data
- [ ] `python backend/manage.py check --deploy` reports no issues
- [ ] `/api/v1/health/` reports `available: true` — otherwise the OCR binary is
      missing and every upload will fail
- [ ] `/api/v1/health/` reports a non-zero `applicability_conditions` —
      otherwise the legal framework did not load and verdicts are wrong
- [ ] Media persistence decided deliberately: a volume, or an accepted loss of
      uploaded photographs on every deploy
