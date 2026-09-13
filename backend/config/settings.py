"""Django settings.

Every environment-specific or secret value is read from the environment. The
repository contains no credentials; see `.env.example` at the repository root
for the full list of variables, and copy it to `.env` for local development.

A single settings module is used deliberately. Splitting into base/dev/prod
adds indirection this project does not need: the differences between
environments are a handful of values that are already environment-driven.
"""

from pathlib import Path

import environ

# backend/config/settings.py -> backend/ -> repository root
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

env = environ.Env()

# The .env file lives at the repository root, so backend and frontend read
# their configuration from predictable, separate places.
_env_file = REPO_ROOT / ".env"
if _env_file.exists():
    env.read_env(str(_env_file))


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

DEBUG = env.bool("DJANGO_DEBUG", default=False)

# No default. A missing secret key must fail loudly at startup rather than
# silently falling back to a value that is identical in every deployment.
SECRET_KEY = env("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Railway reaches the container with two hostnames nobody would think to put in
# DJANGO_ALLOWED_HOSTS, and Django answers 400 DisallowedHost to both:
#
#   healthcheck.railway.app   the platform's own health probe, documented at
#                             docs.railway.com/guides/healthchecks. A 400 here
#                             fails the deployment - the new container is never
#                             promoted, and the error names a host rather than
#                             the health check, so it reads as a routing bug.
#   RAILWAY_PUBLIC_DOMAIN     the service's generated *.up.railway.app domain,
#                             which is not known until the service exists.
#
# Appended only when RAILWAY_ENVIRONMENT_NAME is present, so this widens nothing
# anywhere else: on a laptop, in CI and on any other host the list is exactly
# what DJANGO_ALLOWED_HOSTS said. A custom domain still goes in that variable.
if env("RAILWAY_ENVIRONMENT_NAME", default=""):
    for _platform_host in (
        "healthcheck.railway.app",
        env("RAILWAY_PUBLIC_DOMAIN", default=""),
    ):
        if _platform_host and _platform_host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_platform_host)

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
]

# One app per bounded responsibility, sized so six people can work in parallel
# without editing the same files. Ownership is documented in ARCHITECTURE.md.
LOCAL_APPS = [
    "apps.core",        # shared base models, health endpoint, error envelope
    "apps.accounts",    # the user model and authentication
    "apps.catalog",     # products and commodity categories
    "apps.images",      # product image ingestion, validation, metadata
    "apps.extraction",  # OCR/ML runs and the extracted label declarations
    "apps.rules",       # the compliance rule catalogue and its validators
    "apps.compliance",  # compliance checks, violations, evidence
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves STATIC_ROOT in a deployment, so the admin has its CSS without a
    # separate web server in front of Django. Placed directly below
    # SecurityMiddleware, as WhiteNoise requires, and above everything else so
    # a static file is answered without running session or auth middleware.
    #
    # It serves STATIC_ROOT and nothing else. MEDIA_ROOT - the uploaded label
    # photographs - is deliberately not reachable through it; see the files
    # section below.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # CorsMiddleware must sit above CommonMiddleware so CORS headers are
    # attached even to responses CommonMiddleware short-circuits.
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Database (PostgreSQL)
# ---------------------------------------------------------------------------

# Two ways in, one of them preferred by managed platforms and the other by a
# developer with a local server. `DATABASE_URL` wins when it is set, because a
# platform that provides one (Railway, Heroku, Fly) provides it complete - and
# a half-overridden connection, where the URL supplies the host and a stale
# DATABASE_NAME supplies the database, is the failure this ordering prevents.
#
# Nothing is hard-coded either way: both branches read the environment, and the
# discrete branch still has no default for NAME, USER or PASSWORD, so a missing
# credential fails at startup instead of connecting somewhere unintended.
_DATABASE_URL = env("DATABASE_URL", default="")

if _DATABASE_URL:
    DATABASES = {"default": env.db_url("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DATABASE_NAME"),
            "USER": env("DATABASE_USER"),
            "PASSWORD": env("DATABASE_PASSWORD"),
            "HOST": env("DATABASE_HOST", default="127.0.0.1"),
            "PORT": env("DATABASE_PORT", default="5432"),
        }
    }

# Applied to whichever branch produced the connection, so the two cannot drift.
# Reuse connections between requests; set to 0 if you later run behind an
# external connection pooler such as PgBouncer.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DATABASE_CONN_MAX_AGE", default=60)
# A reused connection is checked before it is handed to a view. Without this, a
# connection dropped between requests - which is routine behind a managed
# platform's proxy, and cannot happen with CONN_MAX_AGE=0 - surfaces as an
# InterfaceError on a request that did nothing wrong.
DATABASES["default"]["CONN_HEALTH_CHECKS"] = env.bool(
    "DATABASE_CONN_HEALTH_CHECKS", default=True
)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation."
                "UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    # Session auth only, for now. No endpoint in the base structure requires a
    # logged-in user, so adding token/JWT machinery now would be complexity
    # with no caller. `feature/authentication` owns that decision;
    # DEFAULT_PERMISSION_CLASSES below is what makes deferring it safe.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Deny by default. Public endpoints opt in explicitly with
    # `permission_classes = [AllowAny]`, so forgetting to think about
    # permissions fails closed rather than open.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    # One consistent error envelope for every failure.
    # See apps/core/api/exceptions.py and docs/api.md.
    "EXCEPTION_HANDLER": "apps.core.api.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("API_THROTTLE_ANON", default="30/min"),
        "user": env("API_THROTTLE_USER", default="120/min"),
    },
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ["v1"],
}


# ---------------------------------------------------------------------------
# Cache (and what it means for throttling)
# ---------------------------------------------------------------------------

# Django's default, written out rather than left implicit, because DRF's
# throttle counters live in it and that makes the default a deployment
# constraint rather than an internal detail.
#
# LocMemCache is per-process. One worker means one counter and the configured
# rate is the real rate. N workers means N independent counters, so the
# effective limit is roughly N x the configured rate and a caller can exceed it
# by being load-balanced across workers.
#
# The deployment therefore runs a single gunicorn worker by default
# (backend/gunicorn.conf.py), which keeps throttling globally correct. Raising
# WEB_CONCURRENCY above 1 is a deliberate trade: either accept per-worker
# throttling, or point this at a shared backend (Redis, Memcached) first. No
# shared cache is introduced here - there is nothing else in this project that
# needs one, and adding infrastructure to serve a demonstration's rate limiter
# would be the wrong shape.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "legalmetrology-default",
    }
}


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

# Explicit origins only. CORS_ALLOW_ALL_ORIGINS is never enabled, including in
# development, so a permissive setting cannot survive into a deployment.
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"],
)
CORS_ALLOW_CREDENTIALS = True

# Required by Django 4+ for session/CSRF-authenticated requests arriving from
# the Vite dev server on a different port.
CSRF_TRUSTED_ORIGINS = list(CORS_ALLOWED_ORIGINS)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Cookies travel over HTTPS only outside local development. Tying this to DEBUG
# means a deployment with DEBUG=False gets secure cookies without a second
# setting anyone could forget.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# The one path the HTTPS redirect must not apply to. A platform health probe
# reaches the container over plain HTTP on the internal network and does not
# follow redirects; with the redirect applied, `/api/v1/health/` answers 301,
# every probe fails, and the deployment is never promoted - which presents as
# "the deploy hangs and then rolls back", naming nothing.
#
# Narrow on purpose. It is one exact path, it is the endpoint that is already
# public and returns no configuration, no credentials and no user data, and
# every other path still redirects. HSTS is unaffected, so a browser that has
# seen this host once will not issue plain HTTP to it again.
#
# Matched against the path with its leading slash stripped, which is what
# SecurityMiddleware compares against.
SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/$"]

if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Behind a reverse proxy that terminates TLS.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# ---------------------------------------------------------------------------
# Files and uploads
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BACKEND_DIR / "staticfiles"

# How WhiteNoise serves what `collectstatic` wrote.
#
# CompressedManifestStaticFilesStorage hashes each file into its name and
# writes a manifest, so a deployment can send far-future cache headers and a
# changed file still reaches the browser. It requires `collectstatic` to have
# run - a template asking for a file the manifest does not list raises - which
# is why it is used only when DEBUG is False. The Dockerfile runs collectstatic
# at build time, so the manifest is always present in an image.
#
# In development Django serves static files from the apps themselves, so the
# plain storage keeps a fresh clone working with no build step at all.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if not DEBUG
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}

# Uploaded product images are third-party content (trade dress, and sometimes
# incidental personal data). They are stored outside the static tree and are
# git-ignored. In any shared environment set DJANGO_MEDIA_ROOT to storage
# outside the repository.
MEDIA_URL = "media/"
MEDIA_ROOT = Path(
    env("DJANGO_MEDIA_ROOT", default="") or str(BACKEND_DIR / "media")
)

#: Maximum accepted image upload. Enforced by apps.images.validators.
MAX_IMAGE_UPLOAD_SIZE_MB = env.int("MAX_IMAGE_UPLOAD_SIZE_MB", default=10)
MAX_IMAGE_UPLOAD_SIZE_BYTES = MAX_IMAGE_UPLOAD_SIZE_MB * 1024 * 1024

# Reject oversized request bodies before they are buffered, so a large upload
# cannot exhaust memory ahead of application-level validation. The margin
# covers multipart overhead and other form fields.
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_IMAGE_UPLOAD_SIZE_BYTES + (1024 * 1024)
# Anything above this is streamed to a temporary file instead of held in RAM.
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_PERMISSIONS = 0o640

# Upper bound on decoded pixel count, checked by apps.images.validators before
# any full decode. Guards against decompression-bomb images: a few-KB file can
# declare dimensions that expand to gigabytes in memory.
MAX_IMAGE_PIXELS = env.int("MAX_IMAGE_PIXELS", default=50_000_000)


# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
# Timestamps are stored in UTC and converted on display.
USE_TZ = True


# ---------------------------------------------------------------------------
# Extraction (OCR / ML integration)
# ---------------------------------------------------------------------------

# Which pipeline apps.extraction requests from the labelextract registry.
# Resolved at runtime by name and version, so swapping in a real OCR engine is
# a config change here plus a registration in ml/ - no backend code change.
DEFAULT_EXTRACTION_ENGINE_NAME = env(
    "DEFAULT_EXTRACTION_ENGINE_NAME", default="null-engine"
)
DEFAULT_EXTRACTION_ENGINE_VERSION = env(
    "DEFAULT_EXTRACTION_ENGINE_VERSION", default="0.1.0"
)


# ---------------------------------------------------------------------------
# Demonstration mode
# ---------------------------------------------------------------------------

# Opens POST /api/v1/images/ and GET /api/v1/compliance/<id>/ to anonymous
# callers. Nothing else is affected, and every upload still goes through
# apps.images.validators in full.
#
# Default False, deliberately: the API denies by default (see REST_FRAMEWORK
# above), there is no login screen yet, and a demonstration needs the analysis
# endpoints reachable without one. Keeping the default closed means a clone, a
# CI run and any deployment stay locked down, and the permissive value has to
# be set on purpose in a git-ignored .env or a platform variable - the same
# reasoning as CORS_ALLOW_ALL_ORIGINS never being enabled above.
#
# On, it opens five routes - six operations - to anonymous callers, and
# nothing else:
#
#     POST /api/v1/images/                                upload and analyse
#     POST /api/v1/extraction/                            upload and read
#     POST /api/v1/compliance/                            evaluate a reading
#     GET  /api/v1/compliance/ and /api/v1/compliance/<uuid>/
#     GET  /api/v1/compliance/applicability-conditions/
#
# That set is asserted by apps/core/tests/test_demo_mode_scope.py, so it cannot
# widen without a test naming this comment failing first.
#
# Enforced by apps.compliance.api.permissions.IsAuthenticatedOrDemoPublic.
DEMO_PUBLIC_ANALYSIS_API = env.bool("DEMO_PUBLIC_ANALYSIS_API", default=False)


# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

# The suite is pytest (see backend/pytest.ini and .github/workflows/ci.yml).
# `manage.py test` cannot see a pytest function, so it used to discover nothing
# and report "Ran 0 tests ... OK" - a green result from a run that executed
# nothing. This runner refuses that instead, and names the command that works.
# It affects `manage.py test` only; it changes nothing at runtime and nothing
# about how pytest collects or runs.
TEST_RUNNER = "config.test_runner.PytestAwareDiscoverRunner"


# ---------------------------------------------------------------------------
# Compliance rules
# ---------------------------------------------------------------------------

# Where `manage.py load_rules` reads executable rule definitions from.
RULES_DEFINITIONS_DIR = Path(
    env("RULES_DEFINITIONS_DIR", default="") or str(REPO_ROOT / "rules" / "definitions")
)

# Where `manage.py load_legal_framework` reads the legal framework from: the
# instruments, applicability conditions, and the versioned clause-level
# requirements of the Rules themselves. Separate from the directory above
# because the two hold different things - what the law requires, and what this
# software can evaluate - and conflating them is how a system starts claiming
# the second covers the first.
RULES_FRAMEWORK_DIR = Path(
    env("RULES_FRAMEWORK_DIR", default="") or str(REPO_ROOT / "rules" / "framework")
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL = env("DJANGO_LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        # Application logs. Never log image bytes, credentials or full request
        # bodies through these - see docs/security.md.
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "labelextract": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
