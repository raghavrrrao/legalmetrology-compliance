"""Gunicorn configuration for a deployed backend.

Read automatically when gunicorn is started from `backend/`:

    gunicorn config.wsgi:application --config gunicorn.conf.py

A file rather than a long command line, because two of the values below are
decisions with consequences elsewhere in the system - the worker count is what
makes API throttling globally correct, and the timeout is sized against
measured OCR latency - and a command line is not a place to explain either.
"""

import os

# --- where to listen --------------------------------------------------------

# Railway injects PORT and routes to it; it is not set on a laptop, hence the
# default. The host must be 0.0.0.0 rather than 127.0.0.1: a container that
# binds to loopback is unreachable from outside itself, which the platform
# reports as "application failed to respond" and not as a binding mistake.
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"


# --- how many processes -----------------------------------------------------

# ONE worker by default, and that is a correctness decision rather than a
# resource one.
#
# DRF's throttle counters live in Django's cache, which is LocMemCache (see
# config/settings.py). LocMemCache is per-process, so N workers keep N separate
# counters and the effective rate limit becomes roughly N x the configured one.
# With a single worker the configured rate is the real rate.
#
# Raising this is supported and deliberate: set WEB_CONCURRENCY. Before doing
# so on anything public, either accept that throttling becomes per-worker or
# move CACHES onto a shared backend first.
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))

# Threads, not more processes, is how this deployment absorbs concurrent
# uploads. Extraction is a subprocess call to the Tesseract binary that spends
# nearly all of its time waiting, so threads release the GIL for the duration -
# and unlike workers, threads share one process and therefore one throttle
# counter, so this does not reintroduce the problem above.
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"


# --- timeouts ---------------------------------------------------------------

# Gunicorn's default is 30s. Extraction against the Tesseract pipeline measures
# at a 2.2s median (docs/evaluation-results.md), but that is a median over
# prepared photographs; a large image on a small container is slower, and a
# worker killed mid-extraction leaves the image row in PROCESSING with no
# recorded reason. 120s is chosen to be longer than any legitimate single
# extraction and still short enough to reap a genuinely stuck worker.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))

# Keep-alive slightly above the platform proxy's, so the proxy closes idle
# connections rather than racing us to it.
keepalive = 65

# Requests are logged to stdout, where the platform collects them. Access logs
# deliberately carry no request bodies - an uploaded photograph and the text
# read off it must not reach a log; see docs/security.md.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
