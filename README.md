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

- **There is no OCR engine installed.** The extraction pipeline is wiring only.
  It reads no text from images. The API reports `is_placeholder: true` and the
  UI says so on screen.
- **Zero compliance rules are loaded.** We ship none, because none have been
  verified against the authoritative text of the Rules. See
  [`rules/README.md`](rules/README.md).
- **With no rules loaded, no product can be found compliant.** The engine
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
| Image handling | Pillow (validation and metadata) |
| OCR / ML | `labelextract` package — interfaces and contracts only, no models yet |
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
│   ├── pyproject.toml
│   ├── README.md
│   ├── labelextract/    contracts, interfaces, pipeline, registry
│   └── tests/
│
├── rules/             compliance rules as reviewable data
│   ├── README.md
│   ├── SCHEMA.md
│   └── definitions/     currently empty by design
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

The second command installs the local `labelextract` package in editable mode.
**It is a separate command on purpose** — a relative path inside a requirements
file resolves against your current directory, which silently installs the wrong
thing when pip is run from elsewhere.

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

### 8. Load compliance rules

```bash
python backend/manage.py load_rules
```

This currently reports that no rule files were found. **That is the expected
output** — see [`rules/README.md`](rules/README.md) for why the rule set ships
empty.

### 9. Create an admin user (optional)

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
| Frontend shows "Could not reach the backend" | Django is not running, or `VITE_API_BASE_URL` is wrong. |
| Browser console shows a CORS error | The Vite origin is not in `CORS_ALLOWED_ORIGINS`. Vite must be on port 5173. |
| `Port 5173 is already in use` | Another Vite instance is running. `strictPort` is deliberate — a silent fallback port would fail CORS confusingly. |
| DevTools shows a `503` on `/api/v1/health/` on every page load | Expected in development, and not a backend error. React StrictMode double-invokes the effect; the first request is aborted on cleanup, which Django logs as `Broken pipe` and Chrome displays as `503`. The second request returns 200 and is the one rendered. Both disappear in a production build. |
| Backend tests return `301` to `https://testserver/...` | `SECURE_SSL_REDIRECT` is on whenever `DJANGO_DEBUG=False` (how CI runs), and the Django test client speaks plain HTTP. `backend/conftest.py` disables it for the suite; if you see this, that fixture was removed or bypassed. It is **not** an `APPEND_SLASH` problem — that produces a *relative* `Location` with the path changed, not an absolute `https://` one. |
| "Try again" does not recover after the backend was actually down | Reload the page. Measured in Chrome: once a connection to `localhost:8000` has been refused, an in-page retry keeps failing without reaching Django, while a fresh document succeeds immediately. The retry logic itself is correct and covered by `src/hooks/useApiHealth.test.jsx`. |
