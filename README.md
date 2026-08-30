# Legal Metrology Compliance Checker

Smart India Hackathon 2026 project.

## Problem statement

> Software System to check compliance of Packaged Commodities under Legal
> Metrology (Packaged Commodities) Rules, 2011 by scanning products, images and
> labels.

## What this system does

A user photographs a packaged product's label. The system extracts the printed
declarations from the image, determines which compliance rules apply to that
commodity, checks the extracted declarations against those rules, and returns a
result that shows **what was found, which rule it relates to, and where on the
package it was read from**.

The design goal is that a user can always ask *"why?"* and get a real answer.
"The AI says non-compliant" is not an output this system is able to produce.

## What this system does NOT do — read this before demoing

This branch is the **base structure**. It is honest about its own limits, and
those limits are enforced by tests rather than only documented:

- **The shipped default still reads no text.** An OCR engine (Tesseract 5) is
  now implemented and selectable, but `null-engine` remains the default until a
  developer installs the binary and switches two values in `.env` — so a fresh
  clone reports `is_placeholder: true` and the UI says so on screen, rather than
  appearing to have OCR it cannot actually run. See
  [`ml/README.md`](ml/README.md).
- **Installing an engine is not measuring one.** No accuracy, character error
  rate or field-extraction F1 has been computed for it on any dataset, so none
  is quoted anywhere.
- **Field extraction is English-only and partial.** Product name, brand,
  generic name, manufacturer address and unit sale price are **not** extracted.
  The unsupported list is derived from the code rather than maintained by hand,
  so it cannot drift away from what the system actually does.
- **Six compliance rules ship, and only two are evaluated.** They come from
  rule 6 of the Rules, verified against the Department of Consumer Affairs'
  consolidated text. The other four are recorded but inactive: three because
  the present category taxonomy cannot express their exemptions, and one
  because the extractor does not read the declaration it names. Legibility under rule 9(1)(a),
  and the rule 3 / rule 26 scope limits, are not modelled at all. See
  [`rules/README.md`](rules/README.md) and [`rules/SOURCES.md`](rules/SOURCES.md).
- **The legal sourcing is not finished.** An amendment-chain gap between March
  2022 and December 2025 is unresolved, and no named human reviewer has
  counter-signed the rule text yet. Both are recorded in
  [`rules/SOURCES.md`](rules/SOURCES.md).
- **With no applicable rule, no product can be found compliant.** The engine
  returns `REVIEW_REQUIRED`, which means "nobody has checked this" — never
  "this is fine".
- **This tool is not a legal determination.** It assists a human reviewer. It
  does not certify compliance, and it is not authoritative merely because it
  uses automation.
- We publish **no accuracy, precision, recall or OCR error-rate figures**,
  because none have been measured.

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite 7, React Router, Vitest |
| Backend | Python 3.11+, Django 5.2, Django REST Framework 3.16 |
| Database | PostgreSQL 14+ |
| Image handling | Pillow (upload validation, metadata, OCR preprocessing) |
| OCR | Tesseract 5 via `pytesseract` — free, offline, CPU-only, no model weights |
| Field extraction | Deterministic patterns in `labelextract.fields` — no LLM, no learned model |
| Rules | JSON definitions in `rules/`, loaded into PostgreSQL |

## Repository structure

```
/
├── frontend/          React + Vite application
│   ├── package.json
│   ├── package-lock.json    committed - npm is the package manager
│   ├── eslint.config.js
│   ├── .env.example
│   └── src/
│       ├── components/  reusable presentational components
│       ├── config/      env.js - the only reader of import.meta.env
│       ├── hooks/       data-loading hooks
│       ├── layouts/     page shell
│       ├── pages/       route targets
│       ├── services/    apiClient.js + one module per API area
│       ├── styles/
│       └── utils/
│
├── backend/           Django project
│   ├── manage.py
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── pytest.ini
│   ├── conftest.py          shared test fixtures
│   ├── config/              settings, root URLs, WSGI/ASGI, API v1 routing
│   └── apps/
│       ├── core/        base models, health endpoint, error envelope
│       ├── accounts/    the user model
│       ├── catalog/     Product, ProductCategory
│       ├── images/      ProductImage, upload validation, safe storage
│       ├── extraction/  ExtractionRun, ExtractedLabelField, the ML seam
│       ├── rules/       ComplianceRule, validators, the rule loader
│       └── compliance/  ComplianceCheck, violations, evidence, the engine
│
├── ml/                OCR / ML boundary
│   ├── pyproject.toml       no required dependencies; [ocr] extra for engines
│   ├── README.md            what the OCR layer does, and what it does not
│   └── labelextract/
│       ├── contracts.py     the stable data boundary
│       ├── interfaces.py    preprocessor / OCR engine / field extractor
│       ├── pipeline.py      stage ordering and failure policy
│       ├── registry.py      name+version -> pipeline
│       ├── cli.py           run a pipeline over one local image
│       ├── baseline/        the placeholder engine (reads no pixels)
│       ├── preprocessing/   Pillow preparation
│       ├── ocr/             Tesseract adapter
│       └── fields/          patterns, normalisation, rule-based extraction
│
├── rules/             compliance rules as reviewable data
│   ├── README.md
│   ├── SCHEMA.md
│   ├── SOURCES.md       what each rule was verified against
│   ├── INVENTORY.md     every LMPC requirement and whether we can check it
│   └── definitions/     six rules from rule 6; two active
│
├── docs/              API, security, ML-integration and strategy docs
├── .github/workflows/ CI: backend, ML and frontend on every pull request
├── .env.example
├── .gitignore
├── README.md
├── CONTRIBUTING.md
└── ARCHITECTURE.md
```

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | **3.11 or newer** | Verified on 3.11.1. The code uses `X \| Y` type syntax. |
| Node.js | **20.19+ or 22.12+** | Verified on v24.14.0. Required by Vite 7. |
| npm | 10+ | Verified on 11.9.0. **npm is the package manager — do not use pnpm or yarn.** |
| PostgreSQL | **14 or newer** | Verified on 16.0. Must be running before you migrate. |
| Git | any recent | |

Check what you have:

```bash
python --version
node --version
npm --version
psql --version
```

---

## Setup

Every command below is run **from the repository root** unless stated otherwise.

### 1. Clone and enter the project

```bash
git clone https://github.com/raghavrrrao/legalmetrology-compliance.git
cd legalmetrology-compliance
```

### 2. Create and activate a Python virtual environment

```bash
python -m venv .venv
```

Activate it:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```
```bat
:: Windows cmd
.venv\Scripts\activate
```
```bash
# macOS / Linux
source .venv/bin/activate
```

> If PowerShell blocks the activation script, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

### 3. Install Python dependencies

```bash
pip install -r backend/requirements-dev.txt
pip install -e ./ml
```

`requirements-dev.txt` includes `requirements.txt`, so this installs both the
runtime and test dependencies. For a deployment, use `requirements.txt` alone.

This is enough to run **every test in the repository**. It is deliberately not
enough to run OCR: `labelextract` has no required dependencies, so a teammate
who is not working on the ML layer installs nothing extra.

The second command installs the local `labelextract` package in editable mode.
**It is a separate command on purpose** — a relative path inside a requirements
file resolves against your current directory, which silently installs the wrong
thing when pip is run from elsewhere.

### 3a. Install the OCR engine — only if you are running OCR

Skip this unless you need to read text from images. Everything else, including
the full test suite, works without it.

```bash
pip install -e "./ml[ocr]"
```

Then install the Tesseract binary and its language data, which are **not**
Python packages and are not vendored here:

| Platform | Command |
|---|---|
| Windows | [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) — it does not add itself to `PATH`; add `C:\Program Files\Tesseract-OCR` yourself |
| macOS | `brew install tesseract tesseract-lang` |
| Debian / Ubuntu | `sudo apt install tesseract-ocr tesseract-ocr-hin` |

Confirm with `tesseract --version`, then switch the backend over in `.env`:

```
DEFAULT_EXTRACTION_ENGINE_NAME=tesseract
DEFAULT_EXTRACTION_ENGINE_VERSION=0.1.0
```

`/api/v1/health/` will then report `is_placeholder: false`, and the UI's "no OCR
engine is installed" notice disappears on its own.

To try it without a database or a web server:

```bash
python -m labelextract.cli path/to/label.jpg
```

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 5. Configure environment variables

Two files, for two different trust levels.

**Backend** (secrets live here; never committed):

```powershell
Copy-Item .env.example .env     # PowerShell
```
```bash
cp .env.example .env            # macOS / Linux
```

Then edit `.env` and set at minimum:

- `DJANGO_SECRET_KEY` — generate one with:
  ```bash
  python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
  ```
- `DATABASE_PASSWORD` — your local PostgreSQL password.

**Frontend** (public configuration; compiled into the browser bundle):

```powershell
Copy-Item frontend\.env.example frontend\.env
```
```bash
cp frontend/.env.example frontend/.env
```

The default `VITE_API_BASE_URL` works for local development.

> **Never put a secret in `frontend/.env`.** Vite inlines every `VITE_`
> variable into the JavaScript bundle, where anyone can read it.

### 6. Create the database

Make sure PostgreSQL is running, then:

```bash
psql -U postgres -c "CREATE DATABASE legalmetrology;"
```

The name must match `DATABASE_NAME` in your `.env`.

### 7. Run migrations

```bash
python backend/manage.py migrate
```

### 8. Seed the product categories

```bash
python backend/manage.py seed_categories
```

Creates the internal grouping codes (`packaged-commodity`, `packaged-food`,
`packaged-non-food`) that rule files reference. **This must run before
`load_rules`**: the loader rejects a rule naming a category that has no row,
rather than silently widening the rule to every commodity. Idempotent.

These are an internal taxonomy for deciding which rules apply — not categories
defined by the Rules.

### 9. Load compliance rules

```bash
python backend/manage.py load_rules
```

This loads six rules and reports each one. Two are active; four load with
`is_active: false` and are never evaluated — see
[`rules/README.md`](rules/README.md) for why, and
[`rules/SOURCES.md`](rules/SOURCES.md) for what they were verified against.
Add `--dry-run` to validate the files without writing.

### 10. Create an admin user (optional)

```bash
python backend/manage.py createsuperuser
```

---

## Running the project

Two terminals, both with the virtualenv active where relevant.

**Terminal 1 — backend** (http://localhost:8000):

```bash
python backend/manage.py runserver
```

**Terminal 2 — frontend** (http://localhost:5173):

```bash
cd frontend
npm run dev
```

Open http://localhost:5173. The home page shows the backend connection status.
If it says it cannot reach the backend, that is the first thing to fix.

Check connectivity directly at any time:

```bash
curl http://localhost:8000/api/v1/health/
```

---

## Running the tests

```bash
# Backend (needs PostgreSQL running - it creates a test database)
cd backend
pytest

# ML contracts (no database or Django needed)
cd ml
pytest

# Frontend
cd frontend
npm test
```

Lint and production build:

```bash
cd frontend
npm run lint      # ESLint; npm run lint:fix applies safe fixes
npm run build
```

All five commands run in CI on every pull request
(`.github/workflows/ci.yml`), against a real PostgreSQL service container. If
CI needs a command that is not documented here, one of the two is wrong.

---

## Development workflow

1. **Update main first.**
   ```bash
   git checkout main
   git pull origin main
   ```
2. **Branch** using the convention in [CONTRIBUTING.md](CONTRIBUTING.md):
   ```bash
   git checkout -b feature/ocr-processing
   ```
3. **Find where your feature belongs.** [ARCHITECTURE.md](ARCHITECTURE.md) maps
   every responsibility to the app that owns it. Work inside your app's
   directory; changes to shared files need a heads-up to the team.
4. **Write tests** alongside the code.
5. **Run the full suite** before opening a PR — backend, ml and frontend.
6. **Update documentation** in the same commit as the behaviour it describes.
7. **Open a pull request into `main`.** Never push to `main` directly.

## Further reading

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layers, data flow, ownership boundaries |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branching, PRs, secrets, dependencies |
| [rules/README.md](rules/README.md) | How compliance rules are authored and verified |
| [ml/README.md](ml/README.md) | How to plug in a real OCR engine |
| [docs/api.md](docs/api.md) | API conventions and the error envelope |
| [docs/security.md](docs/security.md) | Upload validation, secrets, threat notes |
| [docs/ai-ml-strategy.md](docs/ai-ml-strategy.md) | What AI does and does not decide |
| [docs/data-strategy.md](docs/data-strategy.md) | Training, evaluation, demo and legal reference data |
| [docs/evaluation-strategy.md](docs/evaluation-strategy.md) | How performance will be measured |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ImproperlyConfigured: Set the DJANGO_SECRET_KEY environment variable` | No `.env` at the repository root, or the key is missing. See step 5. |
| `connection refused` on port 5432 | PostgreSQL is not running. |
| `password authentication failed` | `DATABASE_PASSWORD` in `.env` does not match your PostgreSQL user. |
| `ModuleNotFoundError: No module named 'labelextract'` | You skipped `pip install -e ./ml`. |
| Extraction runs end `failed` with `engine_not_available` | Tesseract or `pytesseract` is missing. Run `pip install -e "./ml[ocr]"` and install the binary — see step 3a. On Windows, the installer does not add it to `PATH`. |
| Extraction runs end `empty` on a photo that clearly has text | Expected on hard packaging: foil, curvature, glare, low light and small print all defeat Tesseract. `EMPTY` means "unreadable", and the compliance engine correctly treats it as inconclusive rather than as a missing declaration. Retake closer and flatter. |
| Extraction runs end `failed` with `image_too_large` | The image is over 10 MB or 50 MP. Both limits are configurable (`MAX_IMAGE_UPLOAD_SIZE_MB`, `MAX_IMAGE_PIXELS`) and are enforced again inside `ml/`, which is also callable without Django. |
| Text is recognised but no declarations are found | Most likely correct behaviour, not a bug. Declarations are matched only when an anchoring keyword is present, and several — product name, brand, address, unit price — are not extracted at all. See [`ml/README.md`](ml/README.md). |
| Frontend shows "Could not reach the backend" | Django is not running, or `VITE_API_BASE_URL` is wrong. |
| Browser console shows a CORS error | The Vite origin is not in `CORS_ALLOWED_ORIGINS`. Vite must be on port 5173. |
| `Port 5173 is already in use` | Another Vite instance is running. `strictPort` is deliberate — a silent fallback port would fail CORS confusingly. |
| DevTools shows a `503` on `/api/v1/health/` on every page load | Expected in development, and not a backend error. React StrictMode double-invokes the effect; the first request is aborted on cleanup, which Django logs as `Broken pipe` and Chrome displays as `503`. The second request returns 200 and is the one rendered. Both disappear in a production build. |
| Backend tests return `301` to `https://testserver/...` | `SECURE_SSL_REDIRECT` is on whenever `DJANGO_DEBUG=False` (how CI runs), and the Django test client speaks plain HTTP. `backend/conftest.py` disables it for the suite; if you see this, that fixture was removed or bypassed. It is **not** an `APPEND_SLASH` problem — that produces a *relative* `Location` with the path changed, not an absolute `https://` one. |
| "Try again" does not recover after the backend was actually down | Reload the page. Measured in Chrome: once a connection to `localhost:8000` has been refused, an in-page retry keeps failing without reaching Django, while a fresh document succeeds immediately. The retry logic itself is correct and covered by `src/hooks/useApiHealth.test.jsx`. |
