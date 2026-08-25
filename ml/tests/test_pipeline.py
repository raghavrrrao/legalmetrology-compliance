"""Pipeline behaviour, including the guarantees that keep extraction honest."""

import pytest

from labelextract import registry
from labelextract.baseline import null_engine
from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ExtractionStatus,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
)
from labelextract.exceptions import EngineNotAvailableError, InvalidImageError
from labelextract.interfaces import FieldExtractor, OcrEngine
from labelextract.pipeline import ExtractionPipeline


class _StubOcrEngine(OcrEngine):
    """An engine with a fixed answer. Tests the pipeline, not recognition."""

    name = "stub-ocr"
    version = "0.0.0"

    def __init__(self, ocr: OcrResult | None = None, raises: Exception | None = None):
        self._ocr = ocr if ocr is not None else OcrResult()
        self._raises = raises

    def recognise(self, image: ImageRef) -> OcrResult:
        if self._raises is not None:
            raise self._raises
        return self._ocr


class _StubFieldExtractor(FieldExtractor):
    name = "stub-fields"
    version = "0.0.0"

    def extract(self, ocr: OcrResult, image: ImageRef):
        return (
            ExtractedField(
                key=LabelFieldKey.NET_QUANTITY,
                raw_value="500 g",
                confidence=0.9,
                box=BoundingBox(x=1, y=1, width=10, height=5),
            ),
        )


def test_pipeline_requires_an_ocr_engine():
    with pytest.raises(ValueError):
        ExtractionPipeline(name="empty", version="0.0.0", ocr_engine=None)


# --- the placeholder must never look like a real reading --------------------


def test_null_engine_returns_no_text_and_no_fields(image_ref):
    pipeline = registry.get_pipeline(null_engine.NAME, null_engine.VERSION)
    result = pipeline.run(image_ref)

    assert result.status is ExtractionStatus.EMPTY
    assert result.ocr.blocks == ()
    assert result.ocr.full_text == ""
    assert result.fields == ()


def test_placeholder_flag_propagates_to_the_result(image_ref):
    pipeline = registry.get_pipeline(null_engine.NAME, null_engine.VERSION)
    result = pipeline.run(image_ref)

    assert result.is_placeholder is True
    assert result.engine_name == null_engine.NAME
    assert result.engine_version == null_engine.VERSION


def test_null_engine_reports_a_missing_file_as_a_failure_not_as_empty(tmp_path):
    """A broken storage path must not be indistinguishable from a blank label."""
    pipeline = registry.get_pipeline(null_engine.NAME, null_engine.VERSION)
    missing = ImageRef(
        path=tmp_path / "gone.png", image_format="png", size_bytes=0
    )
    result = pipeline.run(missing)

    assert result.status is ExtractionStatus.FAILED
    assert result.error_code == "invalid_image"


def test_processing_time_is_recorded(image_ref):
    pipeline = registry.get_pipeline(null_engine.NAME, null_engine.VERSION)
    assert pipeline.run(image_ref).processing_ms >= 0


# --- status semantics -------------------------------------------------------


def test_recognised_text_with_no_fields_is_completed_not_empty(image_ref):
    """'Readable but the declaration is absent' differs from 'unreadable'.

    The compliance engine must be able to tell them apart: only the first is
    evidence about the package.
    """
    pipeline = ExtractionPipeline(
        name="stub",
        version="0.0.0",
        ocr_engine=_StubOcrEngine(OcrResult(blocks=(TextBlock(text="Some text"),))),
        field_extractor=None,
    )
    result = pipeline.run(image_ref)

    assert result.status is ExtractionStatus.COMPLETED
    assert result.fields == ()


def test_full_pipeline_with_field_extraction(image_ref):
    pipeline = ExtractionPipeline(
        name="stub",
        version="0.0.0",
        ocr_engine=_StubOcrEngine(OcrResult(blocks=(TextBlock(text="Net Qty 500 g"),))),
        field_extractor=_StubFieldExtractor(),
    )
    result = pipeline.run(image_ref)

    assert result.status is ExtractionStatus.COMPLETED
    assert result.is_placeholder is False
    assert result.field_for(LabelFieldKey.NET_QUANTITY).raw_value == "500 g"
    assert result.metadata["field_extraction_ran"] is True


# --- failure handling -------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (InvalidImageError("bad"), "invalid_image"),
        (EngineNotAvailableError("missing"), "engine_not_available"),
    ],
)
def test_known_errors_become_failed_results(image_ref, error, expected_code):
    pipeline = ExtractionPipeline(
        name="stub", version="0.0.0", ocr_engine=_StubOcrEngine(raises=error)
    )
    result = pipeline.run(image_ref)

    assert result.status is ExtractionStatus.FAILED
    assert result.error_code == expected_code
    assert result.fields == ()


def test_unexpected_exceptions_are_not_swallowed(image_ref):
    """A bug in an engine must surface, not be logged as 'unreadable image'."""
    pipeline = ExtractionPipeline(
        name="stub",
        version="0.0.0",
        ocr_engine=_StubOcrEngine(raises=ZeroDivisionError("bug in engine")),
    )
    with pytest.raises(ZeroDivisionError):
        pipeline.run(image_ref)
