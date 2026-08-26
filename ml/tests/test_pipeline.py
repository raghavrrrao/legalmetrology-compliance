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
from labelextract.exceptions import (
    EngineNotAvailableError,
    InvalidImageError,
    PreprocessingError,
)
from labelextract.interfaces import FieldExtractor, ImagePreprocessor, OcrEngine
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


# --- preprocessing is a separate stage with its own lifecycle ---------------


class _StubPreprocessor(ImagePreprocessor):
    """Writes a real file, so the pipeline's cleanup can actually be observed."""

    name = "stub-preprocessor"
    version = "0.0.0"

    def __init__(self, tmp_path, raises: Exception | None = None):
        self._tmp_path = tmp_path
        self._raises = raises
        self.released: list[ImageRef] = []
        self.produced: ImageRef | None = None

    def process(self, image: ImageRef) -> ImageRef:
        if self._raises is not None:
            raise self._raises
        path = self._tmp_path / "prepared.png"
        path.write_bytes(image.path.read_bytes())
        self.produced = ImageRef(
            path=path, image_format="png", size_bytes=path.stat().st_size,
            width=2, height=2,
        )
        return self.produced

    def release(self, processed: ImageRef) -> None:
        self.released.append(processed)
        processed.path.unlink(missing_ok=True)


def test_the_ocr_engine_receives_the_preprocessed_image(image_ref, tmp_path):
    """Otherwise the preparation work is silently discarded."""
    seen = {}

    class _Recording(_StubOcrEngine):
        def recognise(self, image):
            seen["path"] = image.path
            return OcrResult()

    preprocessor = _StubPreprocessor(tmp_path)
    ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_Recording(), preprocessor=preprocessor,
    ).run(image_ref)

    assert seen["path"] == preprocessor.produced.path


def test_the_intermediate_is_released_after_a_successful_run(image_ref, tmp_path):
    """A long-running server must not accumulate a copy of every upload."""
    preprocessor = _StubPreprocessor(tmp_path)
    ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(), preprocessor=preprocessor,
    ).run(image_ref)

    assert len(preprocessor.released) == 1
    assert not preprocessor.produced.path.exists()


def test_the_intermediate_is_released_after_a_failed_run(image_ref, tmp_path):
    preprocessor = _StubPreprocessor(tmp_path)
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(raises=InvalidImageError("bad")),
        preprocessor=preprocessor,
    ).run(image_ref)

    assert result.status is ExtractionStatus.FAILED
    assert len(preprocessor.released) == 1


def test_the_original_image_is_never_released(image_ref):
    """`release` deletes files. Handing it the evidence would destroy it."""

    class _PassThrough(_StubPreprocessor):
        def process(self, image: ImageRef) -> ImageRef:
            return image

    preprocessor = _PassThrough(None)
    ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(), preprocessor=preprocessor,
    ).run(image_ref)

    assert preprocessor.released == []
    assert image_ref.path.exists()


def test_a_preprocessing_failure_is_recorded_not_raised(image_ref, tmp_path):
    preprocessor = _StubPreprocessor(tmp_path, raises=PreprocessingError("no"))
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(), preprocessor=preprocessor,
    ).run(image_ref)

    assert result.status is ExtractionStatus.FAILED
    assert result.error_code == "preprocessing_failed"


# --- metadata records how a result was produced -----------------------------


def test_metadata_names_every_component_that_ran(image_ref, tmp_path):
    """So a disappointing run is diagnosable later without re-running it."""
    pipeline = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(OcrResult(blocks=(TextBlock(text="x"),))),
        preprocessor=_StubPreprocessor(tmp_path),
        field_extractor=_StubFieldExtractor(),
    )
    metadata = pipeline.run(image_ref).metadata

    assert metadata["preprocessor_name"] == "stub-preprocessor"
    assert metadata["ocr_engine_name"] == "stub-ocr"
    assert metadata["field_extractor_name"] == "stub-fields"


def test_metadata_exposes_a_resize_that_would_move_bounding_boxes(
    image_ref, tmp_path
):
    """When these differ, boxes are in preprocessed space, not source space.

    Recording both is what makes that detectable rather than a silent
    mismatch between an evidence overlay and the photograph under it.
    """
    metadata = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(),
        preprocessor=_StubPreprocessor(tmp_path),
    ).run(image_ref).metadata

    assert metadata["source_dimensions"] == [4, 4]
    assert metadata["preprocessed_dimensions"] == [2, 2]


def test_metadata_reports_no_preprocessed_dimensions_when_none_ran(image_ref):
    metadata = ExtractionPipeline(
        name="stub", version="0.0.0", ocr_engine=_StubOcrEngine()
    ).run(image_ref).metadata

    assert metadata["preprocessed"] is False
    assert metadata["preprocessed_dimensions"] is None
