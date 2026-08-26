"""The Django <-> ML seam, now that there is a real engine behind it.

`test_extraction_service.py` covers the placeholder path. This file covers what
changes when a pipeline actually reads text and reports declarations: the
fields, their normalised values, their geometry, and the uncertainty flags all
have to survive the trip into PostgreSQL without being flattened.

No Tesseract binary is involved. A fake pipeline is registered in the
`labelextract` registry and resolved by name exactly as a real one is, so the
service, the status mapping and the persistence code under test are the real
ones - only recognition is stubbed. That is the same reason the ML tests use a
fake runner: a test that needed Tesseract installed would fail on half the
team's machines and would be measuring recognition rather than integration.
"""

import pytest
from django.conf import settings

from labelextract import registry
from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
)
from labelextract.exceptions import OcrFailureError
from labelextract.interfaces import FieldExtractor, OcrEngine
from labelextract.ocr import tesseract as tesseract_pipeline
from labelextract.pipeline import ExtractionPipeline

from apps.extraction.models import ExtractionRun
from apps.extraction.services import extraction_service
from apps.images.models import ProductImage

pytestmark = pytest.mark.django_db

_READING_PIPELINE = "backend-test-reading"
_FAILING_PIPELINE = "backend-test-ocr-failure"
_TEST_VERSION = "0.0.0"


class _ReadingOcrEngine(OcrEngine):
    """Returns a fixed reading of a plausible back panel."""

    name = "backend-test-ocr"
    version = _TEST_VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        lines = [
            "SUNRISE CLASSIC BISCUITS",
            "Net Qty: 500 g",
            "M.R.P. Rs. 250.00 (incl. of all taxes)",
            "Batch No: B24X117",
            "Mfg Date: 25/12/2024",
            "Country of Origin: India",
        ]
        return OcrResult(
            blocks=tuple(
                TextBlock(
                    text=text,
                    box=BoundingBox(x=4, y=4 + index * 20, width=300, height=18),
                    confidence=0.87,
                )
                for index, text in enumerate(lines)
            ),
            raw={"engine": "backend-test-ocr", "line_count": len(lines)},
        )


class _AmbiguousFieldExtractor(FieldExtractor):
    """Emits one certain field and one explicitly uncertain one."""

    name = "backend-test-fields"
    version = _TEST_VERSION

    def extract(self, ocr: OcrResult, image: ImageRef):
        return (
            ExtractedField(
                key=LabelFieldKey.NET_QUANTITY,
                raw_value="Net Qty: 500 g",
                normalized_value={
                    "quantity": 500,
                    "unit": "g",
                    "base_quantity": 500,
                    "base_unit": "g",
                    "uncertain": False,
                },
                confidence=0.87,
                box=BoundingBox(x=4, y=24, width=300, height=18),
            ),
            ExtractedField(
                key=LabelFieldKey.DATE_OF_MANUFACTURE,
                raw_value="Mfg Date: 03/04/2025",
                normalized_value={
                    "uncertain": True,
                    "uncertainty_reasons": [
                        "both DD/MM and MM/DD are valid readings of this date"
                    ],
                    "candidates": ["2025-04-03", "2025-03-04"],
                },
                # An engine that reported no confidence for this reading.
                confidence=None,
                box=None,
            ),
        )


class _FailingOcrEngine(OcrEngine):
    name = "backend-test-failing-ocr"
    version = _TEST_VERSION

    def recognise(self, image: ImageRef) -> OcrResult:
        raise OcrFailureError("tesseract timed out")


def _register(name: str, build) -> None:
    """Register once per process; the registry rejects duplicates on purpose."""
    if (name, _TEST_VERSION) not in list(registry.available_pipelines()):
        registry.register_pipeline(name, _TEST_VERSION, build)


_register(
    _READING_PIPELINE,
    lambda: ExtractionPipeline(
        name=_READING_PIPELINE,
        version=_TEST_VERSION,
        ocr_engine=_ReadingOcrEngine(),
        field_extractor=_AmbiguousFieldExtractor(),
    ),
)
_register(
    _FAILING_PIPELINE,
    lambda: ExtractionPipeline(
        name=_FAILING_PIPELINE,
        version=_TEST_VERSION,
        ocr_engine=_FailingOcrEngine(),
    ),
)


def _run(image: ProductImage, pipeline: str) -> ExtractionRun:
    return extraction_service.run_extraction(
        image, engine_name=pipeline, engine_version=_TEST_VERSION
    )


# --- a run that reads text --------------------------------------------------


def test_recognised_text_is_persisted(product_image):
    run = _run(product_image, _READING_PIPELINE)

    assert run.status == ExtractionRun.Status.COMPLETED
    assert "Net Qty: 500 g" in run.recognised_text
    assert run.is_placeholder is False


def test_a_real_reading_advances_the_image_to_processed(product_image):
    _run(product_image, _READING_PIPELINE)
    product_image.refresh_from_db()

    assert product_image.status == ProductImage.Status.PROCESSED


def test_extracted_fields_become_rows(product_image):
    run = _run(product_image, _READING_PIPELINE)

    keys = set(run.fields.values_list("field_key", flat=True))
    assert keys == {"net_quantity", "date_of_manufacture"}


def test_normalised_values_survive_into_the_database(product_image):
    run = _run(product_image, _READING_PIPELINE)
    quantity = run.fields.get(field_key="net_quantity")

    assert quantity.normalized_value["base_quantity"] == 500
    assert quantity.normalized_value["base_unit"] == "g"
    assert quantity.raw_value == "Net Qty: 500 g"


def test_geometry_survives_so_the_ui_can_show_the_evidence(product_image):
    run = _run(product_image, _READING_PIPELINE)
    quantity = run.fields.get(field_key="net_quantity")

    assert quantity.bounding_box == {"x": 4, "y": 24, "width": 300, "height": 18}


def test_uncertainty_is_not_flattened_on_the_way_into_the_database(product_image):
    """The whole point of marking a reading uncertain is that it stays marked.

    If this were lost at the persistence layer, an ambiguous date would reach
    the compliance engine and the UI looking exactly like a confident one.
    """
    run = _run(product_image, _READING_PIPELINE)
    date = run.fields.get(field_key="date_of_manufacture")

    assert date.normalized_value["uncertain"] is True
    assert date.normalized_value["candidates"] == ["2025-04-03", "2025-03-04"]
    assert date.normalized_value["uncertainty_reasons"]


def test_an_unreported_confidence_is_stored_as_null_not_zero(product_image):
    """NULL means 'unknown'. Zero would mean 'the engine was certain it erred'."""
    run = _run(product_image, _READING_PIPELINE)

    assert run.fields.get(field_key="net_quantity").confidence == pytest.approx(0.87)
    assert run.fields.get(field_key="date_of_manufacture").confidence is None


def test_run_metadata_records_which_components_ran(product_image):
    """So a disappointing result is diagnosable without re-running it."""
    run = _run(product_image, _READING_PIPELINE)
    metadata = run.raw_output["metadata"]

    assert metadata["ocr_engine_name"] == "backend-test-ocr"
    assert metadata["field_extractor_name"] == "backend-test-fields"
    assert run.raw_output["block_count"] == 6


# --- a run that fails -------------------------------------------------------


def test_an_ocr_engine_failure_is_recorded_with_its_stable_code(product_image):
    """`ocr_failed` is distinct from `invalid_image`: it is not the user's fault.

    The frontend branches on this code, so "retake the photo" and "the OCR
    service fell over" must not arrive as the same message.
    """
    run = _run(product_image, _FAILING_PIPELINE)

    assert run.status == ExtractionRun.Status.FAILED
    assert run.error_code == "ocr_failed"
    assert run.fields.count() == 0
    product_image.refresh_from_db()
    assert product_image.status == ProductImage.Status.FAILED


# --- the real Tesseract pipeline, without running Tesseract -----------------


def test_the_tesseract_pipeline_is_resolvable_by_name_and_version():
    """Registration is what makes it selectable from `.env` with no code change."""
    assert (
        tesseract_pipeline.NAME,
        tesseract_pipeline.VERSION,
    ) in list(registry.available_pipelines())


def test_building_the_tesseract_pipeline_needs_no_ocr_stack_installed():
    """Its dependencies are resolved on first use, not at import.

    That is what lets `manage.py check`, the health endpoint and this test suite
    run on a machine with neither Pillow nor Tesseract present.
    """
    pipeline = registry.get_pipeline(
        tesseract_pipeline.NAME, tesseract_pipeline.VERSION
    )

    assert pipeline.is_placeholder is False
    assert pipeline.preprocessor is not None
    assert pipeline.field_extractor is not None


def test_selecting_tesseract_clears_the_placeholder_flag_on_the_health_endpoint(
    settings,
):
    """The UI's "no OCR engine is installed" notice disappears on its own."""
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = tesseract_pipeline.NAME
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = tesseract_pipeline.VERSION

    assert extraction_service.default_pipeline_is_placeholder() is False


def test_the_shipped_default_is_still_the_placeholder():
    """A fresh clone must not appear to have OCR it cannot actually run.

    Switching to Tesseract is a deliberate `.env` change made once the binary
    is installed - never a silent default that fails on first upload.
    """
    assert settings.DEFAULT_EXTRACTION_ENGINE_NAME == "null-engine"


# --- the two format allowlists must not drift apart -------------------------


def test_the_ml_format_allowlist_matches_the_upload_validator():
    """`ml/` cannot import Django, so the lists are duplicated - and checked.

    A format the uploader accepts but the preprocessor rejects would produce an
    upload that always fails at extraction, with nothing at the upload boundary
    explaining why.
    """
    from labelextract.preprocessing.pillow_preprocessor import SUPPORTED_FORMATS

    from apps.images.constants import ALLOWED_FORMATS

    assert set(ALLOWED_FORMATS) <= SUPPORTED_FORMATS
