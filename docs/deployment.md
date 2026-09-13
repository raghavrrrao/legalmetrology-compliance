# Deployment

How this system is deployed, what it needs, and — just as importantly — what
it does **not** yet do safely in a deployment. Read the limitations section
before promising anything to anyone.

Target: the Django/DRF backend on **Railway** with **Railway PostgreSQL**. The
React frontend is a static bundle hosted separately.

**Status: verified ready to deploy. Not deployed.** No Railway project has been
created from this repository, nothing has been pushed to one, and no public
HTTPS endpoint exists. Nothing below may be described as live.

Last verification pass: **2026-09-09**, on the `feature/railway-deployment`
branch. What was actually executed, and what was not:

| | Result |
| --- | --- |
| Backend suite (`pytest`, PostgreSQL) | 819 passed |
| ML suite (`pytest`) | 575 passed |
| Frontend `npm run lint` / `npm run build` / `npm test` | pass / pass / 202 passed |
| `manage.py check --deploy` (`DJANGO_DEBUG=False`) | 0 issues, 0 silenced |
| `manage.py makemigrations --check` | no changes detected |
| `deploy_setup` run twice against PostgreSQL | identical counts, exit 0 - idempotent |
| Health probe simulated as Railway sends it | 200, payload correct |
| `railway.json` against the official Railway schema | validates |
| **Docker image build** | **NOT RUN - no Docker on the verifying machine** |
| **Deployment to Railway** | **NOT RUN** |

The image is built and exercised by the `container` job in
`.github/workflows/ci.yml` on every push to `main` and every PR, including the
check that the Tesseract binary is really in it. That job - not a laptop - is
the standing evidence that the image is sound. If you need local proof before
deploying, run the commands in [Building the image locally](#building-the-image-locally).

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

#### The complete variable list

All 32 variables the code reads, checked against `config/settings.py` and
`gunicorn.conf.py` on 2026-09-09. `.env.example` documents every one of them and
documents nothing that is not read. **Required** means the deployment is wrong
without it — either it will not start, or it will start and be quietly useless.

**Required**

| Variable | Why it is required |
| --- | --- |
| `DJANGO_SECRET_KEY` | No default. The process refuses to start without it, deliberately. |
| `DATABASE_URL` | Set it to `${{Postgres.DATABASE_URL}}`. Wins over the discrete `DATABASE_*` variables whenever it is set. |
| `DJANGO_DEBUG` | `False`. Already the default, set explicitly so it is visible in the dashboard. Also switches cookies to HTTPS-only. |
| `CORS_ALLOWED_ORIGINS` | Defaults to `localhost:5173`. Left alone, the deployed frontend is blocked by CORS and cannot call the API at all. |
| `DEFAULT_EXTRACTION_ENGINE_NAME` | `tesseract`. Left alone, the deployment runs `null-engine` and reads nothing off any label while looking healthy. |
| `DEFAULT_EXTRACTION_ENGINE_VERSION` | `0.3.0`. The pipeline's version, not the binary's. |

Alternative to `DATABASE_URL`, and only if you are not using a managed
database: `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD` (no defaults),
`DATABASE_HOST`, `DATABASE_PORT`. Do not set both forms.

**Decisions with safe defaults — set them when you mean to**

| Variable | Default | Set it when |
| --- | --- | --- |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | You have a custom domain. The two Railway hostnames are appended automatically — see below. |
| `DEMO_PUBLIC_ANALYSIS_API` | `False` | You are deliberately running a public demonstration. Read [Demonstration mode](#demonstration-mode) first. |
| `DJANGO_SECURE_HSTS_SECONDS` | `31536000` | Set `0` for the first deploy. Browsers cache HSTS hard and a wrong value is painful to undo. |
| `DJANGO_MEDIA_ROOT` | `backend/media` | You mounted a volume. See [Media storage](#media-storage--read-this-before-storing-anything-real). |

**Optional — defaults are correct for this deployment**

| Variable | Default | |
| --- | --- | --- |
| `DJANGO_SECURE_SSL_REDIRECT` | `True` | Read only when `DEBUG=False`. |
| `DJANGO_LOG_LEVEL` | `INFO` | Application loggers. |
| `DATABASE_CONN_MAX_AGE` | `60` | Set `0` behind an external pooler. |
| `DATABASE_CONN_HEALTH_CHECKS` | `True` | Leave on behind a managed proxy. |
| `API_THROTTLE_ANON` | `30/min` | Also the ceiling on a public demo. |
| `API_THROTTLE_USER` | `120/min` | |
| `MAX_IMAGE_UPLOAD_SIZE_MB` | `10` | |
| `MAX_IMAGE_PIXELS` | `50000000` | Decompression-bomb guard. |
| `RULES_DEFINITIONS_DIR` | `<root>/rules/definitions` | The image puts these at `/app/rules`. |
| `RULES_FRAMEWORK_DIR` | `<root>/rules/framework` | |
| `WEB_CONCURRENCY` | `1` | **Read [Workers and throttling](#workers-throttling-and-why-there-is-one-worker) before raising this.** |
| `GUNICORN_THREADS` | `4` | |
| `GUNICORN_TIMEOUT` | `120` | Sized against measured OCR latency. |
| `GUNICORN_LOG_LEVEL` | `info` | |

**Supplied by the platform — never set these yourself**

`PORT`, `RAILWAY_ENVIRONMENT_NAME`, `RAILWAY_PUBLIC_DOMAIN`. Defining your own
`PORT` stops Railway routing to the right one.

**No secret belongs in `docs/`, in `.env.example`, or in any `VITE_` variable.**
Generate `DJANGO_SECRET_KEY` per environment and paste it into the Railway
dashboard only.

### 3. Deploy

Railway builds the image, runs `deploy_setup` as the pre-deploy command, starts
gunicorn, and probes `/api/v1/health/` until it answers 200.

### 4. Production smoke test

Run all five. The deployment is not verified until each one passes, and a green
build is not a substitute for any of them — a container that built perfectly
still fails every upload if the pre-deploy command did not run.

**1. Health, and what the two OCR flags mean**

```bash
curl -sS https://<your-service>.up.railway.app/api/v1/health/
```

Required in the response:

| Field | Required value | What a wrong value means |
| --- | --- | --- |
| `status` | `"ok"` | Anything else and a dependency is down; the two `dependencies` entries say which. |
| `dependencies.database` | `"ok"` | PostgreSQL is unreachable — check the `DATABASE_URL` reference. |
| `extraction_engine.is_placeholder` | `false` | You are running `null-engine`. Nothing is read off any label. Set `DEFAULT_EXTRACTION_ENGINE_NAME`. |
| `extraction_engine.available` | `true` | A real pipeline is configured but the Tesseract binary did not answer. The image is wrong, not the config. |
| `compliance_rules.applicability_conditions` | not `0` | `load_legal_framework` did not run. **Verdicts will be wrong, not absent** — see the initialisation section. |
| `compliance_rules.active_total` | `11` | Fewer means `load_rules` loaded a partial set. |

`is_placeholder: false` alone means a real pipeline is *configured*. `available:
true` is what says the binary answered. **Both**, or you are not doing OCR.

**2. HTTPS and the redirect are working**

```bash
curl -sS -o /dev/null -w '%{http_code}
' http://<your-service>.up.railway.app/api/v1/products/
```

Expect `301`. Every path except `/api/v1/health/` redirects to HTTPS; the health
path is exempt so the platform's plain-HTTP probe can reach it.

**3. An unknown Host is refused**

```bash
curl -sS -o /dev/null -w '%{http_code}
' -H 'Host: not-your-domain.example'   https://<your-service>.up.railway.app/api/v1/health/
```

Expect `400`. A `200` means `DJANGO_ALLOWED_HOSTS` is too wide.

**4. The API denies by default**

```bash
curl -sS -o /dev/null -w '%{http_code}
' https://<your-service>.up.railway.app/api/v1/compliance/
```

Expect `403` with `DEMO_PUBLIC_ANALYSIS_API=False`, and `200` with it on. This
is also how you confirm the demo switch took effect after changing it —
[know which position it is in](#demonstration-mode), deliberate or not.

> Use exactly that path. An URL the API does not route — `compliance/history/`,
> say — answers `404` from the catch-all in either position, so a smoke test
> written against one would report "not public" on a deployment that is.

**5. Uploaded media is not served**

```bash
curl -sS -o /dev/null -w '%{http_code}
' https://<your-service>.up.railway.app/media/
```

Expect `404`. Django serves `MEDIA_URL` only when `DEBUG=True`, and WhiteNoise
serves `STATIC_ROOT` only. A `200` here means `DJANGO_DEBUG` is not `False`.

Finally, read the pre-deploy log. `deploy_setup` prints its five counts and the
line `A loaded requirement is not an evaluated one`. If you cannot find that
output, the command did not run and the database is not initialised.

---

## Rollback and redeploy

Railway keeps previous deployments and can promote one back. What matters here
is which parts of a rollback are actually reversible.

**Redeploying** the same commit re-runs the build, then `deploy_setup`, then
starts gunicorn. `deploy_setup` is idempotent — verified by running it twice
against PostgreSQL and getting identical counts — so redeploying is safe at any
time and is the first thing to try after fixing an environment variable. A
changed variable alone does **not** take effect until a redeploy.

**Rolling back the application** is a dashboard action: pick the previous
deployment and promote it. The image is immutable and pinned, so the code and
the Tesseract binary go back exactly.

**What does not roll back:**

- **Applied migrations.** Promoting an older image does not un-apply them.
  Django will run against a schema newer than the code expects. If the rollback
  crosses a destructive migration (a dropped or renamed column), the old code
  breaks and the fix is forward, not backward. Check `git log` on
  `backend/apps/*/migrations/` before assuming a rollback is clean.
- **Uploaded images.** They are on an ephemeral filesystem, so a redeploy
  discards them whether or not it is a rollback. See the media section.
- **Rules and framework rows.** Both loaders are upserts, not replacements. A
  rollback re-runs the older files over the newer rows; a rule *removed* between
  the two versions stays in the database rather than disappearing.

**If the deploy never goes live**, it failed in one of three places and the log
says which:

| Symptom | Cause |
| --- | --- |
| Build fails | Dockerfile or dependencies. Nothing was promoted; the old deployment is still serving. |
| Pre-deploy exits non-zero | `deploy_setup` refused. **This is working as designed** — a half-initialised database stops the deploy instead of silently changing verdicts. Read the step it names. |
| Health check never passes | The container started but `/api/v1/health/` did not answer 200 within `healthcheckTimeout` (300s). Usually a `400 DisallowedHost`, or `available: false` because the OCR pipeline is configured but the binary is missing. |

In all three the previous deployment keeps serving. A failed deploy is not an
outage.

---

## Building the image locally

Optional, and not possible everywhere — the machine that last verified this
branch had no Docker installed, which is why the CI `container` job is the
standing evidence rather than a local build.

```bash
docker build --tag legalmetrology-backend:local .
docker run --rm legalmetrology-backend:local tesseract --version
docker run --rm legalmetrology-backend:local test -f /app/backend/staticfiles/staticfiles.json
docker run --rm legalmetrology-backend:local test -f /app/rules/framework/applicability_conditions.json
```

These four are exactly what `.github/workflows/ci.yml` runs, plus one more there
that resolves the real OCR pipeline inside the image. Do not report an image as
verified on the strength of a successful `docker build` alone: an image missing
the Tesseract binary builds, starts, reports a non-placeholder engine, and fails
every upload.

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
| **A Railway volume** | Mount one at `/app/backend/media` and set `DJANGO_MEDIA_ROOT=/app/backend/media`. Photographs survive deploys. | A volume binds the service to a single replica. That is already the case here for throttling reasons, so it costs nothing extra today. **Check write permissions on the first upload** — see below. |
| **Object storage (S3 or similar)** | Durable and shareable across replicas. | **Not currently possible without a code change.** `build_image_ref` requires a local path; a remote storage backend raises `NotImplementedError` for `.path` and every extraction would fail as `invalid_image`. Adopting it means changing the extraction service to stream bytes rather than open a path. |

**If you mount a volume, verify one upload before trusting it.** The container
runs as `appuser` (uid 10001), not root — see the Dockerfile. The image creates
and chowns `/app/backend/media` at build time, but a volume mounted at that path
covers that directory with the volume's own root, whose ownership is the
platform's to decide and not something this repository can set. If it lands
root-owned, the directory is unwritable by the runtime user and the first upload
fails on a permission error rather than on anything to do with validation. This
has not been observed here — no volume has been mounted, because nothing has
been deployed — so treat it as the first thing to check rather than as a known
defect. If it does happen, mounting the volume at a different path and pointing
`DJANGO_MEDIA_ROOT` at it is the smaller change.

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

`DEMO_PUBLIC_ANALYSIS_API` **defaults to `False`** and should stay False unless
the deployment is deliberately a public demonstration. It is an environment
variable, never a code change: nothing in the repository turns it on.

### What it opens

Exactly five routes become reachable by anonymous callers — the frontend's
workflow, end to end, and nothing else:

| Route | What the demo needs it for |
|---|---|
| `GET /api/v1/compliance/applicability-conditions/` | The declarable facts the scan form asks about |
| `POST /api/v1/extraction/` | Upload a label, read it with Tesseract |
| `POST /api/v1/compliance/` | Evaluate a reading against the loaded rules |
| `GET /api/v1/compliance/<uuid>/` | Open a stored result by its link |
| `GET /api/v1/compliance/` | The inspections history list |

`POST /api/v1/images/` (the one-shot upload-and-analyse path) is the same
permission and is open too; the frontend uses the two-step path above instead.

`GET /api/v1/health/` was already public and is unaffected. **Everything else
stays authenticated**, and the Django admin is not in this switch's reach at
all — it is a DRF permission class, and admin does not use one. That set is
pinned by `backend/apps/core/tests/test_demo_mode_scope.py`, so it cannot widen
without a failing test.

### What becomes true when you turn it on

Said out loud rather than discovered:

- **Analysis becomes anonymous.** No account, no login, no identity recorded —
  which is the point for a demonstration where judges should not have to sign
  up, and is exactly why it is wrong for a service holding real submissions.
- Anyone with the URL can upload a photograph and consume OCR and database
  capacity, **bounded only by the anonymous throttle** (`API_THROTTLE_ANON`,
  30/min). The throttle is not relaxed by this switch and is the demonstration's
  only defence against a script; it is asserted against a demo-opened endpoint
  in the test named above.
- Anonymous results are a **shared pool**: everyone using the demonstration can
  read every result created anonymously. Authenticated users' results stay
  private to them — `CallerScopedCheckQuerysetMixin` enforces that regardless of
  this flag, and an anonymous caller asking for a signed-in user's result gets a
  404, not a 403.
- **Uploads are still validated in full**: format allowlist, real image
  decoding, maximum file size, maximum pixel count. Nothing about validation,
  logging or UUID identifiers is relaxed.

### Turning it on for the SIH demonstration

Set it in the Railway service variables — not in code, not in a committed file:

```
DEMO_PUBLIC_ANALYSIS_API=True
```

Railway redeploys on a variable change; the flag is read per request, so the
new value is live as soon as the new instance is serving. Confirm with
`GET /api/v1/health/` (which answers either way) and then with an anonymous
`GET /api/v1/compliance/applicability-conditions/`, which returns `403` before
the change and `200` after it.

**Turn it back off when the demonstration is over.** Demo access is not a
substitute for authentication on a public service: it is a deliberate,
time-boxed relaxation for an audience that must not be asked to create
accounts. If persistent private user data is ever introduced, this switch must
be `False` and real authenticated access built first — the anonymous shared
pool described above has no way to separate one person's submissions from
another's.

Enabling it changes **API access only**. The compliance engine, its rules, its
determinism and its traceability are untouched by it, and a demonstration
running in this mode is no more legally authoritative than one running
authenticated.

---

## Frontend deployment

The frontend is a static Vite bundle, and the API it calls is compiled into it.

| Where | File Vite reads | `VITE_API_BASE_URL` |
|---|---|---|
| `npm run dev` | `frontend/.env` (copied from `.env.example`) | `http://localhost:8000/api/v1/` |
| `npm run build` | `frontend/.env.production` (committed) | `https://legalmetrology-compliance-production.up.railway.app/api/v1/` |

So a production build needs no arguments:

```bash
cd frontend
npm run build
```

Then host `frontend/dist/` anywhere static (Netlify, Vercel, Cloudflare Pages,
GitHub Pages, or a second Railway service).

To build against a different backend, override on the command line — a shell
variable beats both files:

```bash
VITE_API_BASE_URL="https://<other-service>.up.railway.app/api/v1/" npm run build
```

Five things to know:

- **The value is baked in at build time**, not read at runtime. Changing the API
  URL means **rebuilding and redeploying the frontend**, not editing an
  environment variable on the host.
- **`/api/v1/` is part of the value**, not something the code appends. Services
  request paths relative to it (`health/`, `compliance/`), so an origin on its
  own sends every request to the site root.
- **A build with no value fails** rather than falling back to localhost — in
  `vite.config.js` at build time, and again in `src/config/env.js` if a bundle
  is produced some other way. A deployed page pointed at `localhost:8000` asks
  each visitor's own computer for the API, which looks like an outage nobody
  can reproduce.
- `frontend/.env.production` is **committed on purpose**: it holds a public URL,
  and every `VITE_`-prefixed variable is readable in the shipped bundle anyway.
  That is not licence to add anything else — never put a secret in any file
  under `frontend/`.
- The trailing slash matters and is normalised by `src/config/env.js` if you
  forget it.

Whatever origin the frontend ends up on must be added to the backend's
`CORS_ALLOWED_ORIGINS`, exactly, with scheme and no trailing slash — including
`http://localhost:5173` while testing a local frontend against the deployed
API. Until it is there, every request fails in the browser with a CORS error
and the health card reports the backend as unreachable; the API itself is fine
and `curl` against it will say so.

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

## Security notes for a deployment

`docs/security.md` is the full account. This section is only the part that is
decided by *how it is deployed*, and what was checked on 2026-09-09.

Verified on this branch:

- `manage.py check --deploy` with `DJANGO_DEBUG=False` reports **0 issues**.
  That covers `DEBUG`, the secret key, `SECURE_SSL_REDIRECT`, HSTS, the cookie
  flags and `ALLOWED_HOSTS`.
- `DJANGO_SECRET_KEY` has **no default**. A deployment missing it fails at
  startup rather than signing with a value shared by every clone.
- No secret is committed. No `.env` has ever been committed — checked across
  the whole history, not just the working tree. `.env` and `.env.*` are ignored
  by Git, and `.dockerignore` now excludes both **at any depth**, so a `.env` or
  a `*.key` under `backend/` cannot be baked into an image layer either.
- A request with an unrecognised `Host` gets `400`, including on the health
  path. Only `DJANGO_ALLOWED_HOSTS` plus the two Railway hostnames are accepted,
  and those two only when `RAILWAY_ENVIRONMENT_NAME` is present.
- `CORS_ALLOW_ALL_ORIGINS` is never enabled, in any environment. Origins are
  exact strings and `CSRF_TRUSTED_ORIGINS` is derived from them.
- The API **denies by default** (`IsAuthenticated`). Public endpoints opt in one
  at a time.
- Uploads are validated by decoding, not by trusting the extension: extension,
  content type, byte size, pixel count (decompression-bomb guard) and a real
  `Image.verify()`. Oversized bodies are rejected before buffering.
- Throttling is on by default for anonymous and authenticated callers, and the
  single-worker default is what keeps those limits globally true.
- Result ownership is enforced in the queryset, not just the permission class.
  Another user's result is `404`, never `403` — a `403` would confirm the id
  exists.
- The health endpoint returns dependency status only: no paths, no versions, no
  environment values, no database error text, no traceback.
- Uploaded images are never served by the application in a deployment.

Decisions the deployer owns:

- **`DEMO_PUBLIC_ANALYSIS_API`.** Default `False` and it should stay there
  unless the deployment is deliberately a public demonstration. Turning it on
  makes anonymous results a shared pool — everyone using the demo can read every
  anonymously created result. Authenticated users' results stay private
  regardless. Nothing about upload validation is relaxed.
- **`WEB_CONCURRENCY`.** Raising it above 1 multiplies the effective rate limit
  by the worker count until `CACHES` points at a shared backend.
- **HSTS.** Start at `0`, raise once HTTPS is confirmed.

Not solved by deploying, and not claimed to be: there is no authentication UI,
so a public demonstration is unauthenticated by construction. If real
submissions will be stored, add authentication before opening the demo switch.

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
