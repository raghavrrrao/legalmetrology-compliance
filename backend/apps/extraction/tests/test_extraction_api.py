"""`POST /api/v1/extraction/` - the reading, over HTTP, with no verdict.

What is asserted here is the endpoint's own contract, not the pipeline's:

- the reading reaches the client intact - keys, normalised values, confidence,
  geometry, and which engine produced them;
- the response carries **no** compliance verdict, and creates no `Product`;
- a bad request is a 4xx in the standard envelope, and an unreadable
  photograph is *not* a bad request;
- an engine that breaks its own output contract is a 500 with a recorded
  failed run behind it, not a quietly successful-looking empty result.

Recognition is stubbed, and only recognition. Fake pipelines are registered in
the real `labelextract` registry and resolved by name exactly as Tesseract is,
so the view, the serializers, the ingestion path, the validators, the contract
check and the persistence under test are all the real ones. That is the same
approach `test_extraction_service_ocr.py` takes, and for the same reason: a test
that needed Tesseract installed would fail on half the team's machines and would
be measuring recognition rather than integration.

`test_the_real_configured_pipeline_can_be_driven_through_the_endpoint` is the
exception, and deliberately so - it takes the fakes away and runs whatever
engine the repository actually ships, end to end.
"""

import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from labelextract import registry
from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
)
from labelextract.exceptions import OcrFailureError
from labelextract.interfaces import FieldExtractor, OcrEngine
from labelextract.pipeline import ExtractionPipeline

from apps.catalog.models import Product
from apps.compliance.models import ComplianceCheck
from apps.extraction.models import ExtractionRun
from apps.extraction.services.extraction_service import MalformedExtractionResult
from apps.images.models import ProductImage

pytestmark = pytest.mark.django_db

_READING_PIPELINE = "extraction-api-reading"
_FAILING_PIPELINE = "extraction-api-failing"
_MALFORMED_PIPELINE = "extraction-api-malformed"
_TEST_VERSION = "0.0.0"


class _ReadingOcrEngine(OcrEngine):
    """Returns a fixed, plausible reading of a back panel."""

    name = "extraction-api-ocr"
    version = _TEST_VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        lines = [
            "Net Qty: 500 g",
            "M.R.P. Rs. 250.00 (incl. of all taxes)",
        ]
        return OcrResult(
            blocks=tuple(
                TextBlock(
                    text=text,
                    box=BoundingBox(x=4, y=4 + index * 20, width=300, height=18),
                    confidence=0.9,
                )
                for index, text in enumerate(lines)
            ),
            raw={"source": "extraction-api-test"},
        )


class _FailingOcrEngine(OcrEngine):
    """An engine that cannot read the image - an ordinary outcome, not a bug."""

    name = "extraction-api-failing-ocr"
    version = _TEST_VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        raise OcrFailureError("The photograph could not be read")


class _FixedFieldExtractor(FieldExtractor):
    """Reports one certain declaration and one the extractor was unsure of."""

    name = "extraction-api-fields"
    version = _TEST_VERSION

    def extract(self, ocr: OcrResult, image: ImageRef):
        return (
            ExtractedField(
                key=LabelFieldKey.NET_QUANTITY,
                raw_value="Net Qty: 500 g",
                normalized_value={"quantity": 500, "unit": "g", "uncertain": False},
                confidence=0.9,
                box=BoundingBox(x=4, y=4, width=300, height=18),
            ),
            ExtractedField(
                key=LabelFieldKey.RETAIL_SALE_PRICE,
                raw_value="M.R.P. Rs. 250.00 (incl. of all taxes)",
                normalized_value={"uncertain": True, "candidates": [250.0]},
                # This engine reports no confidence for this reading. None must
                # survive as null, never be filled in with a number.
                confidence=None,
            ),
        )


class _MalformedPipeline(ExtractionPipeline):
    """An engine that runs and then breaks its own output contract.

    Not a `LabelExtractError`: this one *worked*, and returned a result whose
    `ocr` is not an `OcrResult`. The service refuses to persist it, which is
    what stops a bug from being filed away as "the photograph was unreadable".
    """

    def run(self, image: ImageRef) -> ExtractionResult:
        return ExtractionResult(
            status=ExtractionStatus.COMPLETED,
            engine_name=self.name,
            engine_version=self.version,
            processing_ms=1,
            ocr="this is not an OcrResult",
            fields=(),
        )


@pytest.fixture(autouse=True)
def _register_test_pipelines():
    """Register the fakes for the duration of the session.

    The registry refuses to replace an existing key, so registration is guarded
    - the suite may run this module more than once. Nothing is unregistered
    afterwards, because `register_pipeline` has no inverse and inventing one
    here would be a change to the ml/ package for a test's convenience. The
    names are prefixed so they cannot collide with the fakes other suites
    register.
    """
    registered = set(registry.available_pipelines())

    def _ensure(name, factory):
        if (name, _TEST_VERSION) not in registered:
            registry.register_pipeline(name, _TEST_VERSION, factory)

    _ensure(
        _READING_PIPELINE,
        lambda: ExtractionPipeline(
            name=_READING_PIPELINE,
            version=_TEST_VERSION,
            ocr_engine=_ReadingOcrEngine(),
            field_extractor=_FixedFieldExtractor(),
        ),
    )
    _ensure(
        _FAILING_PIPELINE,
        lambda: ExtractionPipeline(
            name=_FAILING_PIPELINE,
            version=_TEST_VERSION,
            ocr_engine=_FailingOcrEngine(),
            field_extractor=_FixedFieldExtractor(),
        ),
    )
    _ensure(
        _MALFORMED_PIPELINE,
        lambda: _MalformedPipeline(
            name=_MALFORMED_PIPELINE,
            version=_TEST_VERSION,
            ocr_engine=_ReadingOcrEngine(),
            field_extractor=_FixedFieldExtractor(),
        ),
    )


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    """Run these tests with the demo switch on.

    Its *off* position is asserted explicitly in
    `test_the_endpoint_denies_anonymous_callers_by_default`, so defaulting it
    on here hides nothing - it keeps every other test in this file about the
    reading rather than about authentication.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = True


@pytest.fixture
def reading_pipeline(settings):
    """Point the configured default at the stubbed reading pipeline.

    The endpoint takes no engine argument - which is correct, a client must not
    get to choose the engine - so this is the seam a test uses instead.
    """
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _READING_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION


def _post(
    client,
    image_bytes,
    *,
    filename="label.png",
    content_type="image/png",
    **extra,
):
    payload = {
        "image": SimpleUploadedFile(filename, image_bytes, content_type=content_type),
        **extra,
    }
    return client.post(reverse("v1:label-extract"), payload, format="multipart")


# --- the happy path ----------------------------------------------------------


def test_a_valid_upload_returns_201_with_the_run_that_read_it(
    client, png_bytes, media_root, reading_pipeline
):
    response = _post(client, png_bytes)

    assert response.status_code == 201
    body = response.json()

    assert uuid.UUID(body["id"])
    assert body["status"] == ExtractionRun.Status.COMPLETED
    assert body["produced_usable_output"] is True
    assert body["recognised_text"]


def test_the_declarations_that_were_read_reach_the_client(
    client, png_bytes, media_root, reading_pipeline
):
    """Keys, raw text, normalisation and geometry all survive the trip."""
    body = _post(client, png_bytes).json()

    by_key = {field["field_key"]: field for field in body["fields_read"]}
    assert set(by_key) == {
        LabelFieldKey.NET_QUANTITY.value,
        LabelFieldKey.RETAIL_SALE_PRICE.value,
    }

    quantity = by_key[LabelFieldKey.NET_QUANTITY.value]
    assert quantity["raw_value"] == "Net Qty: 500 g"
    assert quantity["normalized_value"] == {
        "quantity": 500,
        "unit": "g",
        "uncertain": False,
    }
    assert quantity["confidence"] == pytest.approx(0.9)
    assert quantity["bounding_box"] == {"x": 4, "y": 4, "width": 300, "height": 18}


def test_an_uncertain_reading_is_reported_as_uncertain_not_resolved(
    client, png_bytes, media_root, reading_pipeline
):
    """A guess presented as a value cannot later be told from a measurement."""
    body = _post(client, png_bytes).json()

    price = next(
        field
        for field in body["fields_read"]
        if field["field_key"] == LabelFieldKey.RETAIL_SALE_PRICE.value
    )
    assert price["normalized_value"]["uncertain"] is True
    # The engine reported no confidence. Null means "it did not say" - a
    # fabricated number here would make a guess look measured.
    assert price["confidence"] is None


def test_the_response_says_which_engine_read_the_image(
    client, png_bytes, media_root, reading_pipeline
):
    """`is_placeholder` must reach the UI, or wiring output looks like a reading."""
    body = _post(client, png_bytes).json()

    assert body["engine_name"] == _READING_PIPELINE
    assert body["engine_version"] == _TEST_VERSION
    assert body["is_placeholder"] is False


def test_the_stored_image_is_described_in_the_response(
    client, png_bytes, media_root, reading_pipeline
):
    """Measured from the bytes, not taken from what the upload claimed."""
    body = _post(client, png_bytes).json()

    image = body["image"]
    assert uuid.UUID(image["id"])
    assert image["image_format"] == "png"
    assert image["width"] == 64
    assert image["height"] == 64
    assert image["size_bytes"] == len(png_bytes)
    assert image["view_type"] == ProductImage.ViewType.UNSPECIFIED
    assert image["status"] == ProductImage.Status.PROCESSED


def test_the_unread_declaration_channel_is_exposed(
    client, png_bytes, media_root, reading_pipeline
):
    """Present even when empty, so the UI can rely on the key existing.

    Empty means "this engine reported none", never "everything was read".
    """
    body = _post(client, png_bytes).json()

    assert body["unread_declarations"] == []


def test_a_view_type_is_recorded_against_the_stored_image(
    client, png_bytes, media_root, reading_pipeline
):
    body = _post(client, png_bytes, view_type=ProductImage.ViewType.BACK).json()

    assert body["image"]["view_type"] == ProductImage.ViewType.BACK


def test_the_uploading_user_is_recorded_when_there_is_one(
    client, png_bytes, media_root, user, reading_pipeline
):
    client.force_login(user)

    body = _post(client, png_bytes).json()

    assert ProductImage.objects.get(pk=body["image"]["id"]).uploaded_by_id == user.pk


# --- extraction stays separate from compliance -------------------------------


def test_the_response_carries_no_verdict_and_no_findings(
    client, png_bytes, media_root, reading_pipeline
):
    """The architectural rule this endpoint exists to hold.

    A reading is an observation about a photograph. Whether a declaration was
    legally required, and whether its absence is a contravention, is answered
    only by the rule engine from a verified rule. If a `compliance`, `result`
    or `violations` key ever appears here, that separation has been lost.
    """
    body = _post(client, png_bytes).json()

    for forbidden in (
        "compliance",
        "result",
        "result_display",
        "violations",
        "summary",
    ):
        assert forbidden not in body


def test_extracting_creates_no_product_and_no_compliance_check(
    client, png_bytes, media_root, reading_pipeline
):
    """Asking what is written on a photograph must not manufacture a commodity."""
    _post(client, png_bytes)

    assert not Product.objects.exists()
    assert not ComplianceCheck.objects.exists()


def test_a_category_code_changes_nothing_here(
    client, png_bytes, media_root, reading_pipeline
):
    """`category_code` selects which *rules* apply, and this endpoint has none.

    DRF ignores unknown fields rather than rejecting them, so what is asserted
    is that sending one changed nothing - no product was created and no
    category appears in the reading.
    """
    body = _post(client, png_bytes, category_code="packaged-food").json()

    assert "product_category_code" not in body
    assert not Product.objects.exists()


# --- an unreadable photograph is an outcome, not a bad request ---------------


def test_an_engine_failure_is_a_201_carrying_the_failure(
    client, png_bytes, media_root, settings
):
    """The client asked a fair question and gets a real, stored answer.

    A 4xx here would say the *request* was wrong, when the request was fine and
    the photograph was not readable. `produced_usable_output` is how a caller
    tells the two apart.
    """
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _FAILING_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION

    response = _post(client, png_bytes)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == ExtractionRun.Status.FAILED
    assert body["produced_usable_output"] is False
    # The frontend branches on the code, never on the message.
    assert body["error_code"]
    assert body["fields_read"] == []
    assert body["image"]["status"] == ProductImage.Status.FAILED


def test_the_placeholder_engine_says_so_rather_than_looking_like_a_reading(
    client, png_bytes, media_root
):
    """The shipped default performs no recognition. The response must admit it.

    `conftest` pins the configured engine to `null-engine`, which is what a
    fresh clone runs until an OCR engine is selected in `.env`.
    """
    response = _post(client, png_bytes)

    assert response.status_code == 201
    body = response.json()
    assert body["is_placeholder"] is True
    assert body["fields_read"] == []


# --- bad requests ------------------------------------------------------------


def test_a_request_with_no_file_is_a_400_naming_the_field(client, media_root):
    response = client.post(reverse("v1:label-extract"), {}, format="multipart")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "image" in error["details"]


def test_a_file_that_is_not_an_image_is_rejected_and_nothing_is_stored(
    client, media_root, reading_pipeline
):
    """The validators run in full behind the endpoint."""
    response = _post(client, b"this is not a PNG", filename="shell.png")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "image" in error["details"]
    assert not ProductImage.objects.exists()
    assert not ExtractionRun.objects.exists()


def test_a_disallowed_file_type_is_rejected(client, png_bytes, media_root):
    """Real image bytes under a format the allowlist does not carry."""
    response = _post(
        client, png_bytes, filename="label.svg", content_type="image/svg+xml"
    )

    assert response.status_code == 400
    assert not ProductImage.objects.exists()


def test_an_oversized_upload_is_rejected_before_it_is_decoded(
    client, png_bytes, media_root, settings
):
    """The size limit is the application's, not only the transport's."""
    settings.MAX_IMAGE_UPLOAD_SIZE_BYTES = 16

    response = _post(client, png_bytes)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert not ProductImage.objects.exists()


def test_a_truncated_image_is_rejected_rather_than_stored_and_failed(
    client, png_bytes, media_root
):
    """Corrupt bytes are a bad upload, not an unreadable photograph."""
    response = _post(client, png_bytes[: len(png_bytes) // 2])

    assert response.status_code == 400
    assert not ProductImage.objects.exists()


def test_an_unknown_view_type_is_rejected(client, png_bytes, media_root):
    response = _post(client, png_bytes, view_type="sideways")

    assert response.status_code == 400
    assert "view_type" in response.json()["error"]["details"]
    assert not ProductImage.objects.exists()


def test_a_get_is_a_405_in_the_standard_envelope(client):
    response = client.get(reverse("v1:label-extract"))

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


# --- an engine that breaks its contract is a bug, and stays visible ----------


def test_a_malformed_engine_result_is_recorded_then_re_raised(
    client, png_bytes, media_root, settings
):
    """Recorded so the image does not sit in `processing`, then re-raised.

    A contract breach filed away as "the photograph was unreadable" is a bug
    nobody is ever shown.
    """
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _MALFORMED_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION

    with pytest.raises(MalformedExtractionResult):
        _post(client, png_bytes)

    run = ExtractionRun.objects.get()
    assert run.status == ExtractionRun.Status.FAILED
    assert run.error_code == "internal_error"
    assert run.image.status == ProductImage.Status.FAILED


def test_a_malformed_engine_result_leaks_nothing_to_the_client(
    client, png_bytes, media_root, settings
):
    """The same case seen from outside: a 500 with no internals in the body."""
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = _MALFORMED_PIPELINE
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = _TEST_VERSION

    client.raise_request_exception = False
    response = _post(client, png_bytes)

    assert response.status_code == 500
    text = response.content.decode(errors="replace")
    assert "MalformedExtractionResult" not in text
    assert "Traceback" not in text


# --- the permission switch ---------------------------------------------------


def test_the_endpoint_denies_anonymous_callers_by_default(
    client, png_bytes, media_root, settings
):
    """Deny-by-default is the shipped behaviour, and this is what holds it.

    The demo relaxation is one switch covering the analysis endpoints; adding
    an endpoint must not add an unguarded one.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = False

    response = _post(client, png_bytes)

    assert response.status_code in (401, 403)
    assert response.json()["error"]["code"] in (
        "not_authenticated",
        "permission_denied",
    )
    assert not ProductImage.objects.exists()


def test_an_authenticated_user_is_allowed_with_the_switch_off(
    client, png_bytes, media_root, settings, user, reading_pipeline
):
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    client.force_login(user)

    assert _post(client, png_bytes).status_code == 201


# --- one run against the pipeline the repository actually ships --------------


def test_the_real_configured_pipeline_can_be_driven_through_the_endpoint(
    client, png_bytes, media_root
):
    """No fakes: the default engine, resolved from the registry, over HTTP.

    Everything above stubs recognition so it can assert a known reading. This
    one asserts only what is true of *any* engine the repository ships - that
    it resolves, runs, and produces a run the serializers can render - so it
    stays honest whether the configured default is the placeholder or
    Tesseract. It is the test that would catch a registry name, an `ImageRef`
    field or the result contract drifting apart from the backend.
    """
    response = _post(client, png_bytes)

    assert response.status_code == 201
    body = response.json()

    run = ExtractionRun.objects.get(pk=body["id"])
    assert run.engine_name == body["engine_name"]
    assert body["status"] in ExtractionRun.Status.values
    assert isinstance(body["fields_read"], list)
    assert isinstance(body["unread_declarations"], list)
    # Either a number of milliseconds actually measured, or null. Never a
    # plausible-looking default.
    assert body["processing_ms"] is None or body["processing_ms"] >= 0
