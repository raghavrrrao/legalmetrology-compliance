"""Health and service-status endpoint.

Exists so a teammate can confirm in one request that the frontend can reach the
backend, that the backend can reach PostgreSQL, that the extraction pipeline
resolves, and how many compliance rules are loaded. It is the first thing to
check when something is broken and the last thing to check after setup.
"""

import logging

from django.conf import settings
from django.db import connection
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """`GET /api/v1/health/` - liveness and dependency status.

    Public by design: the frontend calls it before any login, and any future
    uptime check needs it. It exposes no configuration values, no package
    versions and no database error text - only whether each dependency
    answered. That keeps it useful to us without being useful to a scanner.

    Returns 200 when every dependency is up and 503 when any is down, so an
    uptime check can rely on the status code alone.
    """

    permission_classes = [AllowAny]
    # A health check that gets rate-limited reports a false outage. Polling is
    # the entire purpose of this endpoint.
    throttle_classes = []

    def get(self, request, *args, **kwargs) -> Response:
        database_ok = _database_is_reachable()
        extraction_ok, extraction_info = _extraction_status()
        rules_info = _rules_status() if database_ok else None

        healthy = database_ok and extraction_ok

        body = {
            "status": "ok" if healthy else "degraded",
            "api_version": "v1",
            "dependencies": {
                "database": "ok" if database_ok else "unavailable",
                "extraction_engine": "ok" if extraction_ok else "unavailable",
            },
            "extraction_engine": extraction_info,
            "compliance_rules": rules_info,
        }
        return Response(
            body,
            status=(
                status.HTTP_200_OK
                if healthy
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
        )


def _database_is_reachable() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        # Logged with a traceback for us. The response says only "unavailable",
        # so a client never sees connection strings or driver internals.
        logger.exception("Health check: database is unreachable")
        return False
    return True


def _extraction_status() -> tuple[bool, dict]:
    """Report the configured OCR pipeline and whether it is a placeholder.

    `is_placeholder` is surfaced deliberately. While it is True the system
    performs no real recognition, and the UI must say so rather than presenting
    wiring output as a reading.
    """
    info = {
        "name": settings.DEFAULT_EXTRACTION_ENGINE_NAME,
        "version": settings.DEFAULT_EXTRACTION_ENGINE_VERSION,
        "is_placeholder": None,
    }
    try:
        # Imported lazily so a broken ML install degrades this endpoint rather
        # than preventing the module from importing at all.
        from apps.extraction.services import extraction_service

        info["is_placeholder"] = extraction_service.default_pipeline_is_placeholder()
    except Exception:
        logger.exception("Health check: extraction pipeline could not be resolved")
        return False, info
    return True, info


def _rules_status() -> dict:
    """Report how many rules are loaded, split by verification status.

    `verified` is what the compliance engine may use to fail a product. When it
    is zero - which it is on a fresh clone - no product can be found
    non-compliant, and this endpoint is where that becomes visible.
    """
    try:
        from apps.rules.models import ComplianceRule

        active = ComplianceRule.objects.filter(is_active=True)
        return {
            "active_total": active.count(),
            "verified": active.filter(
                source_status=ComplianceRule.SourceStatus.VERIFIED
            ).count(),
            "unverified": active.filter(
                source_status=ComplianceRule.SourceStatus.UNVERIFIED
            ).count(),
        }
    except Exception:
        logger.exception("Health check: rule counts could not be read")
        return {"active_total": None, "verified": None, "unverified": None}


class ApiNotFoundView(APIView):
    """Catch-all for unmatched paths under the API prefix.

    Without this, a typo'd API URL never reaches DRF, so Django returns an HTML
    404 - a debug page in development, a bare error page otherwise. The
    frontend would then get HTML where it expects the JSON error envelope.

    Routed last under /api/v1/, so it only ever handles paths no real endpoint
    claimed. AllowAny is required: with the default IsAuthenticated an
    anonymous client would get 403 for a URL that simply does not exist, which
    is both wrong and confusing.
    """

    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        # Raised through DRF's handler so the response uses the standard
        # envelope, whatever the HTTP method was.
        response = self.handle_exception(NotFound())
        self.headers = self.default_response_headers
        return self.finalize_response(request, response, *args, **kwargs)
