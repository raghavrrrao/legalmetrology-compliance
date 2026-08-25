"""The API error envelope.

Every failure must arrive in the same shape, or the frontend needs a different
parser per status code. See docs/api.md.
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import NotFound, Throttled, ValidationError
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.core.api.exceptions import api_exception_handler, build_error_body


def _handle(exc):
    request = APIRequestFactory().get("/")
    return api_exception_handler(exc, {"view": APIView(), "request": request})


def test_envelope_shape():
    body = build_error_body("some_code", "Some message", {"field": ["detail"]})
    assert body == {
        "error": {
            "code": "some_code",
            "message": "Some message",
            "details": {"field": ["detail"]},
        }
    }


def test_validation_errors_go_into_details_not_the_message():
    """One banner from `message`, per-field text from `details`."""
    response = _handle(ValidationError({"image": ["This field is required."]}))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    error = response.data["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "The submitted data was not valid."
    assert error["details"] == {"image": ["This field is required."]}


def test_not_found_is_normalised():
    response = _handle(NotFound())

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data["error"]["code"] == "not_found"
    assert "detail" not in response.data


def test_throttling_tells_the_client_when_to_retry():
    response = _handle(Throttled(wait=42))

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response.data["error"]["code"] == "rate_limited"
    assert response.data["error"]["details"] == {"retry_after_seconds": 42}


def test_unhandled_exceptions_are_not_converted_into_a_success():
    """Returning None lets Django produce a real 500.

    Swallowing an unexpected error into a 200-with-error-body would make
    failures invisible to any client that checks the status code.
    """
    assert _handle(RuntimeError("boom")) is None


@pytest.mark.django_db
def test_unknown_api_route_returns_json_not_html(client):
    """An unmatched API URL must still produce the JSON envelope.

    Without the catch-all route, Django handles this 404 itself and returns
    HTML, which the frontend cannot parse. Asserting the status code alone
    would not have caught that.
    """
    response = client.get("/api/v1/does-not-exist/")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_unknown_api_route_404s_for_anonymous_users_not_403(client):
    """A URL that does not exist must not look like a permissions problem."""
    response = client.post("/api/v1/nope/")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_health_route_is_versioned(client):
    """API paths carry their version, so v2 can be added without breaking v1."""
    assert reverse("v1:health") == "/api/v1/health/"
