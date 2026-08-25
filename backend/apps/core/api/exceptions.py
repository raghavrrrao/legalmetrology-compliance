"""One consistent error envelope for every API failure.

DRF's default error bodies are inconsistent: a validation error is a dict of
field lists, a 404 is `{"detail": "..."}`, and an unhandled exception is HTML.
The frontend would need three parsers. This handler normalises all of them to:

    {
      "error": {
        "code": "validation_error",
        "message": "The submitted data was not valid.",
        "details": {"image": ["This field is required."]}
      }
    }

`code` is a stable machine-readable string - the frontend branches on it.
`message` is human-readable and safe to display. `details` is optional and may
be null.

See docs/api.md for the full list of codes.
"""

import logging
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)

#: Maps DRF exception classes to our stable error codes. Anything not listed
#: falls back to the DRF default code for the exception.
_CODE_BY_EXCEPTION = {
    drf_exceptions.ValidationError: "validation_error",
    drf_exceptions.NotAuthenticated: "not_authenticated",
    drf_exceptions.AuthenticationFailed: "authentication_failed",
    drf_exceptions.PermissionDenied: "permission_denied",
    drf_exceptions.NotFound: "not_found",
    drf_exceptions.MethodNotAllowed: "method_not_allowed",
    drf_exceptions.Throttled: "rate_limited",
    drf_exceptions.UnsupportedMediaType: "unsupported_media_type",
    drf_exceptions.ParseError: "parse_error",
}

_GENERIC_MESSAGE = "An unexpected error occurred."


def build_error_body(
    code: str, message: str, details: Any = None
) -> dict[str, dict[str, Any]]:
    """Build the standard error envelope.

    Exposed so that non-DRF code paths can produce identical bodies.
    """
    return {"error": {"code": code, "message": message, "details": details}}


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    """DRF `EXCEPTION_HANDLER`. Returns None for exceptions DRF cannot handle.

    Returning None lets Django's own handler produce a 500. We deliberately do
    not convert unexpected exceptions into a 200-with-error-body: a failure
    must remain a failure at the HTTP level.
    """
    # Django's ValidationError can escape from model-level `full_clean()` calls.
    # Translate it so it is not mistaken for a server fault.
    if isinstance(exc, DjangoValidationError):
        exc = drf_exceptions.ValidationError(detail=exc.messages)

    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()

    response = drf_exception_handler(exc, context)
    if response is None:
        # Unhandled: log with a traceback for us, return nothing to the client.
        # The generic 500 body is produced by Django, which never leaks the
        # traceback when DEBUG is False.
        logger.exception(
            "Unhandled exception in API view",
            extra={"view": context.get("view").__class__.__name__
                   if context.get("view") else None},
        )
        return None

    code = _resolve_code(exc)
    message, details = _split_message_and_details(exc, response.data)

    if isinstance(exc, drf_exceptions.Throttled) and exc.wait is not None:
        details = {"retry_after_seconds": int(exc.wait)}

    response.data = build_error_body(code, message, details)
    return response


def _resolve_code(exc: Exception) -> str:
    for exception_class, code in _CODE_BY_EXCEPTION.items():
        if isinstance(exc, exception_class):
            return code
    default_code = getattr(exc, "default_code", None)
    return str(default_code) if default_code else "error"


def _split_message_and_details(exc: Exception, data: Any) -> tuple[str, Any]:
    """Derive a human message and optional structured details from DRF's body."""
    if isinstance(exc, drf_exceptions.ValidationError):
        # Field errors belong in `details`; the message stays generic so the
        # frontend can show one banner plus per-field messages.
        return "The submitted data was not valid.", data

    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"]), None

    if isinstance(data, list) and data:
        return str(data[0]), None

    default_detail = getattr(exc, "default_detail", None)
    return str(default_detail) if default_detail else _GENERIC_MESSAGE, data or None
