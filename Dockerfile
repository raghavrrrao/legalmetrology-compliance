# Production image for the Django backend.
#
# Why a Dockerfile rather than the platform's automatic builder
# -------------------------------------------------------------
# One reason, and it is sufficient: **Tesseract is a system binary that pip
# cannot install.** The extraction pipeline shells out to `tesseract`, and an
# automatic Python builder installs Python packages only. A deployment built
# that way comes up with `pytesseract` present, no binary behind it, and an
# engine that is not a placeholder - so nothing in the response looks wrong
# until every single upload fails.
#
# Pinning the image also pins the Python version, the Tesseract version and the
# system libraries underneath both, which is what makes a result reproducible
# rather than dependent on whatever the builder resolved that morning.
#
# Scope: the backend only. The React frontend is a static bundle and is not
# containerised here - see docs/deployment.md.

FROM python:3.11-slim

# 3.11 matches the minimum in README.md, backend/requirements.txt and the CI
# workflow. Bump all four together or not at all.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# --- system packages --------------------------------------------------------
#
# `tesseract-ocr` is the whole reason this file exists. It brings the English
# language data (`eng`) with it, which is the only language the pipeline asks
# for - `TesseractOptions.languages` defaults to `("eng",)`. Adding
# `tesseract-ocr-hin` for Devanagari is a one-word change here plus a change to
# that tuple; it is deliberately not installed speculatively, because an
# uninstalled language pack is a smaller problem than an image carrying data
# nothing requests.
#
# Nothing else is installed: Pillow and psycopg[binary] both ship manylinux
# wheels, so no compiler, no libpq headers, no build-essential.
RUN apt-get update \
    && apt-get install --no-install-recommends --yes tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Python dependencies ----------------------------------------------------
#
# Copied and installed before the application code so that editing a view does
# not reinstall Django. The two installs are separate for the same reason they
# are separate in the README: `labelextract` is its own package with its own
# dependency story, and `[ocr]` is the extra that adds pytesseract.
#
# Not editable (`pip install -e`) here, unlike development. A deployment has no
# reason to import the package from a working tree, and a non-editable install
# fails at build time if the package is broken rather than at first import.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --requirement backend/requirements.txt

COPY ml ./ml
RUN pip install "./ml[ocr]"

# --- application code -------------------------------------------------------
#
# `rules/` is not optional and not documentation. RULES_DEFINITIONS_DIR and
# RULES_FRAMEWORK_DIR default to <repo root>/rules/..., and the repo root
# inside this image is /app - so `load_rules` and `load_legal_framework` read
# from /app/rules. An image without it builds fine and fails at deploy_setup.
COPY backend ./backend
COPY rules ./rules

# --- static files -----------------------------------------------------------
#
# Collected at build time so the image is self-contained: WhiteNoise serves
# what is written here, and the manifest that
# CompressedManifestStaticFilesStorage needs exists before the first request
# rather than being generated on a container that may not have a writable disk.
#
# The three variables below exist only for the length of this one command.
# settings.py reads DJANGO_SECRET_KEY and the database configuration at import
# time and has no defaults for them, so collectstatic cannot import settings
# without something there. Nothing connects to a database and nothing signs
# anything: these values are discarded when the RUN layer ends and are not
# present in the running container, which takes its real values from the
# platform's environment.
RUN DJANGO_SECRET_KEY=build-time-only-never-used-to-sign-anything \
    DJANGO_DEBUG=False \
    DATABASE_URL=postgres://build:build@127.0.0.1:5432/build \
    python backend/manage.py collectstatic --noinput --clear

# --- runtime user -----------------------------------------------------------
#
# Not root. A container process that is compromised through an image upload
# should not also own the filesystem it is running on.
#
# MEDIA_ROOT defaults to /app/backend/media and is created and owned here,
# because the upload path writes to it on the first request and a permission
# error there presents as a failed upload rather than as a setup problem.
# See docs/deployment.md: on this platform that directory does NOT persist
# across deploys unless a volume is mounted over it.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/backend/media \
    && chown -R appuser:appuser /app/backend/media /app/backend/staticfiles
USER appuser

# --- how it starts ----------------------------------------------------------
#
# The port is NOT written here. Railway injects PORT at runtime and it is not
# available at build time, so it is read inside backend/gunicorn.conf.py from
# the environment - which also keeps this command identical whether it runs on
# the platform or on a laptop.
#
# `--chdir` puts /app/backend on sys.path so `config.wsgi` resolves. Absolute
# paths throughout, so this behaves the same regardless of what working
# directory a platform decides to start the container in.
CMD ["gunicorn", "--chdir", "/app/backend", "--config", "/app/backend/gunicorn.conf.py", "config.wsgi:application"]
