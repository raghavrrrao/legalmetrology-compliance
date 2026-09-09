# Deployment

How this system is deployed, what it needs, and — just as importantly — what
it does **not** yet do safely in a deployment. Read the limitations section
before promising anything to anyone.

Target: the Django/DRF backend on **Railway** with **Railway PostgreSQL**. The
React frontend is a static bundle hosted separately.

**Status: ready to deploy, not deployed.** Every file below exists and every
check listed has been run locally. No Railway project has been created from
this repository and no deployment has happened.

---

## The shape of it

```
        React web client  (static bundle, hosted separately)
                 │  HTTPS, VITE_API_BASE_URL
                 ▼
        ┌───────────────────────────────────┐
        │  Railway service  (this Dockerfile)│
        │                                    │
        │  gunicorn ─ Django/DRF             │
        │      ├─ WhiteNoise  (static)       │
        │      ├─ labelextract ─ tesseract   │
        │      └─ compliance rule engine     │
        └───────────────────────────────────┘
                 │
                 ▼
        Railway PostgreSQL
```

One backend, one compliance engine. A future React Native client uses the same
API and changes nothing here — which is the reason the engine lives behind the
API and not in a client.

---

## Files this adds

| File | What it does |
| --- | --- |
| `Dockerfile` | Production image: Python 3.11, **the Tesseract binary**, dependencies, `collectstatic`, non-root user, gunicorn. |
| `.dockerignore` | Keeps `.env`, `.venv`, uploaded media and the frontend out of the image. |
| `railway.json` | Build (Dockerfile), start command, pre-deploy command, health-check path. |
| `backend/gunicorn.conf.py` | Bind address, worker count, threads, timeouts. |
| `backend/apps/core/management/commands/deploy_setup.py` | The one initialisation command. |

---

## The initialisation sequence, and why it is a command

Four commands must run, in this order, before the API can answer correctly:

```
migrate  →  seed_categories  →  load_rules  →  load_legal_framework
```

`load_rules` rejects a rule naming a category that has no row, so seeding comes
first; both loaders need migrated tables.

The fourth one is why this is a command rather than four lines in a deploy
script. **Skipping `load_legal_framework` does not fail.** It leaves a database
with a full set of rules, healthy-looking counts, and no applicability
conditions. Findings then cite no clause and no source, and a clause gated on a
fact nobody stated has no gate to check — so the rule runs anyway and records a
violation. The same photograph answers REVIEW REQUIRED on a correctly loaded
database and PARTIALLY COMPLIANT, with a violation against clause 6(1)(a), on
one missing that step.

So the deployment runs exactly one thing:

```bash
python /app/backend/manage.py deploy_setup
```

It runs all four in order, then **verifies the resulting state** and exits
non-zero if any of the five things a verdict depends on is empty. Railway's
pre-deploy command does not promote a container when it exits non-zero, so a
half-initialised database stops the deploy instead of quietly changing
verdicts. It is idempotent, so it runs on every deploy rather than only the
first.

Never use `--dry-run` for this. A dry run writes nothing, so it would report
success over a database that was never loaded.

---

## Deploying to Railway

### 1. Create the services

In a Railway project:

1. **Add PostgreSQL** (New → Database → PostgreSQL).
2. **Add a service from this repository.** Railway reads `railway.json` and
   builds with the `Dockerfile`; no builder settings need changing.

### 2. Set the service variables

`DATABASE_URL` should be a **reference** to the PostgreSQL service's variable
rather than a copied string, so it follows the database if it is recreated.

| Variable | Value | Notes |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | a fresh generated key | **Required.** Never reuse one from another environment. |
| `DJANGO_DEBUG` | `False` | **Required.** Also switches cookies to HTTPS-only. |
| `DJANGO_ALLOWED_HOSTS` | your custom domain, if any | The generated `*.up.railway.app` domain and `healthcheck.railway.app` are added automatically — see below. |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | A service reference, not a literal. |
| `CORS_ALLOWED_ORIGINS` | the frontend origin, e.g. `https://your-frontend.vercel.app` | Exact origins, comma-separated. No wildcards, ever. |
| `DEFAULT_EXTRACTION_ENGINE_NAME` | `tesseract` | Otherwise the deployment runs the placeholder and reads nothing. |
| `DEFAULT_EXTRACTION_ENGINE_VERSION` | `0.3.0` | The pipeline version, not the binary's. |
| `DEMO_PUBLIC_ANALYSIS_API` | `False` unless you mean it | See [Demonstration mode](#demonstration-mode). |
| `DJANGO_SECURE_HSTS_SECONDS` | `0` for the first deploy | Browsers cache HSTS hard. Raise it once HTTPS is confirmed working. |

Generate a key with:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

`CSRF_TRUSTED_ORIGINS` is **not** a separate variable — it is derived from
`CORS_ALLOWED_ORIGINS` in `config/settings.py`.

### 3. Deploy

Railway builds the image, runs `deploy_setup` as the pre-deploy command, starts
gunicorn, and probes `/api/v1/health/` until it answers 200.

### 4. Verify

```bash
curl https://<your-service>.up.railway.app/api/v1/health/
```

The deployment is genuinely doing OCR only when the response contains **both**:

```json
"is_placeholder": false,
"available": true
```

`is_placeholder: false` alone means a real pipeline is *configured*. `available:
true` is what says the Tesseract binary answered. Also check that
`compliance_rules.applicability_conditions` is not `0` — if it is, the framework
did not load and verdicts will be wrong.

---

## The two hostnames you did not configure

Railway reaches the container with two Host headers that nobody would think to
put in `DJANGO_ALLOWED_HOSTS`, and Django answers `400 DisallowedHost` to both:

- `healthcheck.railway.app` — the platform's health probe. A 400 here fails the
  deployment, and the error names a host rather than the health check, so it
  reads as a routing bug.
- `RAILWAY_PUBLIC_DOMAIN` — the generated `*.up.railway.app` domain, which does
  not exist until the service does.

`config/settings.py` appends both, but **only when `RAILWAY_ENVIRONMENT_NAME`
is set** — so nothing is widened on a laptop, in CI, or on any other host. A
custom domain still goes in `DJANGO_ALLOWED_HOSTS`.

## The one path exempt from the HTTPS redirect

The health probe arrives over plain HTTP on the internal network and does not
follow redirects. With `SECURE_SSL_REDIRECT` applied to it, every probe gets a
301, the health check never passes, and the deploy is rolled back.

`SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/$"]` prevents that. It is one exact
path — the endpoint that is already public and returns no configuration, no
credentials and no user data. Every other path still redirects, and HSTS is
unaffected. Pinned in both directions by
`backend/apps/core/tests/test_https_redirect.py`.

---

## Media storage — read this before storing anything real

**Uploaded product images do not persist on Railway by default.** The container
filesystem is ephemeral: every deploy and every restart replaces it, and
`MEDIA_ROOT` goes with it. Rows in the database survive; the photographs they
point at do not.

They are also not shared. Extraction reads the image through
`ProductImage.image.path` — a local filesystem path — so more than one container
would each hold a different subset of the uploads.

Three options, in the order they should be considered:

| | What it gives you | What it costs |
| --- | --- | --- |
| **Nothing (default)** | Uploads work; the image is analysed and the result stored. The photograph is gone after the next deploy. | Acceptable for a demonstration where results are produced and read in one session. Not acceptable if anyone will come back to the evidence later. |
| **A Railway volume** | Mount one at `/app/backend/media` and set `DJANGO_MEDIA_ROOT=/app/backend/media`. Photographs survive deploys. | A volume binds the service to a single replica. That is already the case here for throttling reasons, so it costs nothing extra today. |
| **Object storage (S3 or similar)** | Durable and shareable across replicas. | **Not currently possible without a code change.** `build_image_ref` requires a local path; a remote storage backend raises `NotImplementedError` for `.path` and every extraction would fail as `invalid_image`. Adopting it means changing the extraction service to stream bytes rather than open a path. |

No object-storage provider has been configured or added as a dependency,
deliberately. It is written down here as a known requirement rather than
invented.

**Uploaded images are never served by the application.** Django serves
`MEDIA_URL` only when `DEBUG=True`, and WhiteNoise serves `STATIC_ROOT` only —
never `MEDIA_ROOT`. A deployed instance returns 404 for `/media/...`, which is
correct: label photographs are third-party content and sometimes carry
incidental personal data.

---

## Workers, throttling, and why there is one worker

DRF's throttle counters live in Django's cache, which is `LocMemCache` — and
`LocMemCache` is **per process**. With N gunicorn workers there are N
independent counters, so the effective limit is roughly N × the configured rate
and a caller can exceed it by being load-balanced between workers.

`backend/gunicorn.conf.py` therefore runs **one worker** with four threads.
Threads share the process, so they share the counter; extraction is a subprocess
call that spends its time waiting, so threads absorb concurrent uploads without
the extra processes.

Raising `WEB_CONCURRENCY` above 1 is supported and deliberate. Before doing it
on anything public, either accept that throttling becomes per-worker, or point
`CACHES` at a shared backend first. Redis has **not** been introduced: nothing
else in this project needs one, and adding infrastructure to serve a
demonstration's rate limiter would be the wrong shape.

---

## Demonstration mode

`DEMO_PUBLIC_ANALYSIS_API=True` opens exactly two things to anonymous callers:

- `POST /api/v1/images/` — upload and analyse
- `GET /api/v1/compliance/<id>/` and the history list — read stored results

It defaults to **False**, and it should stay False unless the deployment is
deliberately a public demonstration. If you turn it on, this is what becomes
true and it should be said out loud:

- Anyone with the URL can upload a photograph and consume OCR and database
  capacity, bounded only by the anonymous throttle (30/min by default).
- Anonymous results are a **shared pool**: everyone using the demonstration can
  read every result created anonymously. Authenticated users' results stay
  private to them — `CallerScopedCheckQuerysetMixin` enforces that regardless of
  this flag.
- Uploads are still validated in full. Nothing about validation is relaxed.

If real submissions will be stored, leave it False and add authentication first.

---

## Frontend deployment

The frontend is a static Vite bundle. Build it with the deployed API's origin:

```bash
cd frontend
VITE_API_BASE_URL="https://<your-service>.up.railway.app/api/v1/" npm run build
```

Then host `frontend/dist/` anywhere static (Netlify, Vercel, Cloudflare Pages,
GitHub Pages, or a second Railway service).

Three things to know:

- **The value is baked in at build time**, not read at runtime. Changing the API
  URL means rebuilding, not editing an environment variable on the host.
- A shell variable **overrides** `frontend/.env`, which is what makes the
  command above work without editing a file.
- Every `VITE_`-prefixed variable is **public** — readable by anyone who opens
  the bundle. Never put a secret there. The trailing slash matters and is
  normalised by `src/config/env.js` if you forget it.

Whatever origin the frontend ends up on must be added to the backend's
`CORS_ALLOWED_ORIGINS`, exactly, with scheme and no trailing slash.

---

## CORS and CSRF are different controls

- **CORS** decides which *browser origins* may read a response from this API.
  Set `CORS_ALLOWED_ORIGINS` to the exact frontend origin.
  `CORS_ALLOW_ALL_ORIGINS` is never enabled, in any environment.
- **CSRF** decides which origins may make *state-changing, cookie-authenticated*
  requests. `CSRF_TRUSTED_ORIGINS` is derived from `CORS_ALLOWED_ORIGINS`, so
  configuring one configures both.

Widening CORS does not fix a CSRF failure and widening CSRF does not fix a CORS
failure. If the browser console says "blocked by CORS policy", it is the first.
If Django says "CSRF verification failed", it is the second.

---

## Running the production configuration locally

Useful before deploying, and the closest thing to a rehearsal.

```bash
# 1. Collect static files (the production storage backend hashes them)
DJANGO_DEBUG=False python backend/manage.py collectstatic --noinput

# 2. Django's deployment audit
DJANGO_DEBUG=False python backend/manage.py check --deploy

# 3. Initialise a database exactly as a deploy would
python backend/manage.py deploy_setup
```

To run the server itself with production settings, set `DJANGO_DEBUG=False` and
`DJANGO_SECURE_SSL_REDIRECT=False` (there is no TLS terminator in front of you
locally), then `python backend/manage.py runserver`.

**Gunicorn does not run on Windows** — it needs POSIX `fcntl`. On Windows, use
the Docker image or `runserver` with the settings above; the WSGI callable is
the same either way.

---

## Limitations, stated plainly

1. **Uploaded images do not persist** without a mounted volume, and object
   storage needs a code change first. See the media section above.
2. **One worker.** Correct for throttling, and a ceiling on throughput. Raising
   it needs a shared cache.
3. **No queue.** Extraction runs inside the request. At a ~2.2 s median
   (`docs/evaluation-results.md`) that is fine; a slower engine or a much larger
   image would need `run_extraction` moved behind a worker.
4. **No authentication UI.** The API denies by default and there is no login
   screen, which is why a public demonstration needs
   `DEMO_PUBLIC_ANALYSIS_API`. That is a gap to close, not a design.
5. **English only.** The pipeline requests `eng`; the image installs only that
   language pack. Bilingual Indian labels are read in English only. Adding
   Devanagari means `tesseract-ocr-hin` in the Dockerfile *and* a change to
   `TesseractOptions.languages`.
6. **A loaded requirement is not an evaluated one.** `deploy_setup` reports 69
   requirements on record; 8 are implemented. `rules/INVENTORY.md` says why for
   each of the rest. The deployment does not change that and must not be
   described as though it did.
