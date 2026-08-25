"""The Django <-> ML seam.

These tests run the real placeholder pipeline through the real service against
a real database row, so the integration is verified rather than assumed.
"""

import pytest

from apps.extraction.models import ExtractionRun
from apps.extraction.services import extraction_service
from apps.images.models import ProductImage

pytestmark = pytest.mark.django_db


def test_run_extraction_persists_a_run(product_image):
    run = extraction_service.run_extraction(product_image)

    assert run.pk is not None
    assert run.engine_name == "null-engine"
    assert run.engine_version == "0.1.0"
    assert run.completed_at is not None
    assert run.processing_ms is not None


def test_placeholder_output_is_flagged_in_the_database(product_image):
    """The flag must survive the trip from the ML layer into the row.

    If it did not, the API could present wiring output as a real reading.
    """
    run = extraction_service.run_extraction(product_image)

    assert run.is_placeholder is True


def test_placeholder_produces_no_text_and_no_fields(product_image):
    """It must not invent readings to make the pipeline look like it worked."""
    run = extraction_service.run_extraction(product_image)

    assert run.status == ExtractionRun.Status.EMPTY
    assert run.recognised_text == ""
    assert run.fields.count() == 0


def test_image_status_advances_to_processed(product_image):
    extraction_service.run_extraction(product_image)
    product_image.refresh_from_db()

    assert product_image.status == ProductImage.Status.PROCESSED


def test_missing_file_is_recorded_as_a_failed_run(product_image):
    """A broken storage path must be visible, not look like a blank label."""
    product_image.image.storage.delete(product_image.image.name)

    run = extraction_service.run_extraction(product_image)

    assert run.status == ExtractionRun.Status.FAILED
    assert run.error_code == "invalid_image"
    product_image.refresh_from_db()
    assert product_image.status == ProductImage.Status.FAILED


def test_multiple_runs_are_kept_for_the_same_image(product_image):
    """Re-running a better engine must not destroy the earlier result.

    Compliance checks reference a specific run; overwriting would leave those
    results citing readings that no longer exist.
    """
    first = extraction_service.run_extraction(product_image)
    second = extraction_service.run_extraction(product_image)

    assert first.pk != second.pk
    assert product_image.extraction_runs.count() == 2


def test_engine_can_be_overridden_per_run(product_image):
    """The engine is a runtime choice, not a schema commitment."""
    run = extraction_service.run_extraction(
        product_image, engine_name="null-engine", engine_version="0.1.0"
    )
    assert run.engine_name == "null-engine"


def test_unknown_engine_is_recorded_as_a_failed_run(product_image):
    """A misconfigured engine name is recorded, not raised.

    `PipelineNotFoundError` is a `LabelExtractError`, so it takes the same path
    as any other extraction failure: the run is persisted with a stable
    `error_code` the operator can act on. Raising instead would leave the image
    stuck in PROCESSING with nothing explaining why.
    """
    run = extraction_service.run_extraction(
        product_image, engine_name="no-such-engine", engine_version="1.0.0"
    )

    assert run.status == ExtractionRun.Status.FAILED
    assert run.error_code == "pipeline_not_found"
    product_image.refresh_from_db()
    assert product_image.status == ProductImage.Status.FAILED


def test_build_image_ref_carries_measured_metadata(product_image):
    ref = extraction_service.build_image_ref(product_image)

    assert ref.image_format == "png"
    assert ref.width == 64
    assert ref.height == 64
    assert ref.path.exists()


def test_default_pipeline_is_reported_as_a_placeholder():
    assert extraction_service.default_pipeline_is_placeholder() is True
