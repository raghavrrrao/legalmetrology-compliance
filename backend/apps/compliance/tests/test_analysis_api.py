"""The two endpoints the demonstration flow runs on.

    POST /api/v1/images/            upload -> verdict, in one request
    GET  /api/v1/compliance/<uuid>/ read one result back

Covered here: the response actually carries what the UI has to render, the
permission switch behaves in both positions, and a bad request is a 4xx in the
standard envelope rather than a 500.

The pipeline fakes come from `test_analysis_service`, so both suites exercise
the same stubbed recognition and there is one place to change it.
"""

import uuid

import pytest
from django.urls import reverse

from labelextract.contracts import LabelFieldKey

from apps.compliance.models import ComplianceCheck
from apps.compliance.tests.test_analysis_service import (  # noqa: F401
    _READING_PIPELINE,
    _TEST_VERSION,
    _register_test_pipelines,
)
from apps.extraction.models import ExtractionRun
from apps.images.models import ProductImage

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    """Run these tests with the demo switch on.

    The switch's *off* position is asserted explicitly in
    `test_the_endpoints_deny_anonymous_callers_by_default`, so defaulting it on
    here does not hide the locked-down behaviour - it just keeps every other
    test in this file about the response rather than about authentication.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = True


@pytest.fixture(autouse=True)
def _use_the_test_pipeline(settings):
    """Point the configured default at the stubbed pipeline.

    The endpoint takes no engine argument - which is correct, a client must not
    choose the engine - so this is the seam a test uses instead.
    """
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _READING_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION


def _upload(client, png_bytes, **extra):
    from django.core.files.uploadedfile import SimpleUploadedFile

    payload = {
        "image": SimpleUploadedFile(
            "label.png", png_bytes, content_type="image/png"
        ),
        **extra,
    }
    return client.post(reverse("v1:image-analyse"), payload, format="multipart")


# --- the happy path ----------------------------------------------------------


def test_upload_returns_201_with_a_complete_result(client, png_bytes, media_root):
    response = _upload(client, png_bytes)

    assert response.status_code == 201
    body = response.json()

    # The verdict and its explanation - neither is optional for the UI.
    assert body["result"] in dict(ComplianceCheck.Result.choices)
    assert body["result_display"]
    assert body["summary"]

    # Enough identity to fetch the result again later.
    assert uuid.UUID(body["id"])


def test_the_response_carries_what_was_read_off_the_label(
    client, png_bytes, media_root
):
    """The extracted and normalised declarations reach the client."""
    body = _upload(client, png_bytes).json()

    extraction = body["extraction"]
    assert extraction["status"] == ExtractionRun.Status.COMPLETED
    assert extraction["produced_usable_output"] is True
    assert extraction["recognised_text"]

    read = extraction["fields_read"]
    assert len(read) == 1
    field = read[0]
    assert field["field_key"] == LabelFieldKey.NET_QUANTITY.value
    assert field["raw_value"] == "Net Qty: 500 g"
    # Normalisation survives the trip into PostgreSQL and back out as JSON.
    assert field["normalized_value"] == {"value": 500, "unit": "g"}
    assert field["confidence"] == pytest.approx(0.9)


def test_the_response_says_which_engine_read_the_image(
    client, png_bytes, media_root
):
    """`is_placeholder` must reach the UI, or wiring output looks like a reading."""
    body = _upload(client, png_bytes).json()

    extraction = body["extraction"]
    assert extraction["engine_name"] == _READING_PIPELINE
    assert extraction["engine_version"] == _TEST_VERSION
    assert extraction["is_placeholder"] is False


def test_a_finding_carries_its_rule_code_reference_and_evidence(
    client, png_bytes, media_root, category, make_rule
):
    """Everything a reviewer needs to check a finding themselves."""
    make_rule(
        code="API-FAIL",
        field_key="consumer_care_contact",
        verified=True,
        legal_reference="Fixture reference - not legal text",
        severity="major",
    )

    body = _upload(client, png_bytes, category_code=category.code).json()

    assert body["result"] == ComplianceCheck.Result.NON_COMPLIANT
    violation = body["violations"][0]
    assert violation["rule_code"] == "API-FAIL"
    assert violation["legal_reference"] == "Fixture reference - not legal text"
    assert violation["severity"] == "major"
    assert violation["field_key"] == "consumer_care_contact"
    assert violation["message"]
    # The text we did read, as justification for the absence.
    assert violation["evidence"][0]["excerpt"]


def test_the_category_that_was_checked_is_reported(
    client, png_bytes, media_root, category
):
    body = _upload(client, png_bytes, category_code=category.code).json()

    assert body["product_category_code"] == category.code


def test_without_a_category_the_response_says_so_with_null(
    client, png_bytes, media_root
):
    """Null is the difference between 'checked and clean' and 'could not check'."""
    body = _upload(client, png_bytes).json()

    assert body["product_category_code"] is None
    assert body["result"] == ComplianceCheck.Result.REVIEW_REQUIRED


def test_the_unread_declaration_channel_is_exposed(
    client, png_bytes, media_root
):
    """Present even when empty, so the UI can rely on the key existing."""
    body = _upload(client, png_bytes).json()

    assert body["extraction"]["unread_declarations"] == []


# --- reading a result back ---------------------------------------------------


def test_a_result_can_be_fetched_again_by_id(client, png_bytes, media_root):
    created = _upload(client, png_bytes).json()

    response = client.get(
        reverse("v1:compliance-detail", kwargs={"pk": created["id"]})
    )

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["result"] == created["result"]


def test_an_unknown_result_id_is_a_404_in_the_standard_envelope(client):
    response = client.get(
        reverse("v1:compliance-detail", kwargs={"pk": uuid.uuid4()})
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- bad requests ------------------------------------------------------------


def test_a_request_with_no_file_is_a_400_naming_the_field(client):
    response = client.post(reverse("v1:image-analyse"), {}, format="multipart")

    assert response.status_code == 400
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert "image" in body["details"]


def test_a_file_that_is_not_an_image_is_rejected(client, media_root):
    """The validators run in full behind the endpoint - nothing is stored."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = client.post(
        reverse("v1:image-analyse"),
        {
            "image": SimpleUploadedFile(
                "shell.png", b"this is not a PNG", content_type="image/png"
            )
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert not ProductImage.objects.exists()


def test_an_unknown_category_code_is_rejected_rather_than_ignored(
    client, png_bytes, media_root
):
    """Silently dropping it would look identical to an unreadable photograph."""
    response = _upload(client, png_bytes, category_code="no-such-category")

    assert response.status_code == 400
    assert "category_code" in response.json()["error"]["details"]
    assert not ProductImage.objects.exists()


def test_an_unknown_view_type_is_rejected(client, png_bytes, media_root):
    response = _upload(client, png_bytes, view_type="sideways")

    assert response.status_code == 400
    assert "view_type" in response.json()["error"]["details"]


# --- the permission switch ---------------------------------------------------


def test_the_endpoints_deny_anonymous_callers_by_default(
    client, png_bytes, settings, media_root
):
    """With the demo switch off, the project's deny-by-default rule holds.

    This is the setting's shipped value, so this test is what stops the
    relaxation from quietly becoming permanent.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = False

    upload = _upload(client, png_bytes)
    detail = client.get(
        reverse("v1:compliance-detail", kwargs={"pk": uuid.uuid4()})
    )

    assert upload.status_code in (401, 403)
    assert detail.status_code in (401, 403)
    assert upload.json()["error"]["code"] in (
        "not_authenticated",
        "permission_denied",
    )
    assert not ProductImage.objects.exists()


def test_an_authenticated_user_is_allowed_with_the_switch_off(
    client, png_bytes, settings, user, media_root
):
    """The relaxation is the only thing the switch changes."""
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    client.force_login(user)

    response = _upload(client, png_bytes)

    assert response.status_code == 201


def test_the_uploading_user_is_recorded_when_there_is_one(
    client, png_bytes, user, media_root
):
    client.force_login(user)

    body = _upload(client, png_bytes).json()

    image = ProductImage.objects.get(pk=body["image"]["id"])
    assert image.uploaded_by_id == user.pk


def test_the_health_endpoint_is_unaffected_by_the_demo_switch(client, settings):
    """The switch must not weaken anything it was not aimed at."""
    settings.DEMO_PUBLIC_ANALYSIS_API = False

    assert client.get(reverse("v1:health")).status_code in (200, 503)
