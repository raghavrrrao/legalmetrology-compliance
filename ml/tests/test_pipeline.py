"""Pipeline behaviour, including the guarantees that keep extraction honest."""

import logging

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
    UnreadDeclaration,
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
    """Both dimension sets are recorded whenever the preprocessor resized.

    The boxes themselves are mapped back to source space (see the section
    below), so this is no longer the only thing standing between an evidence
    overlay and a silent mismatch - but it is what makes the resize visible in
    a stored run months later.
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


# --- boxes come back in the coordinate system of the photograph -------------
#
# The preprocessor may resize, which puts every box the engine reports in the
# intermediate's coordinate system. Nobody downstream knows that happened: the
# UI draws boxes over the *original* photograph, and a reviewer checking a
# disputed reading would be shown the wrong part of the package. These tests
# pin the correction, because a wrong box looks exactly as authoritative as a
# right one.


def _boxed(*boxes: BoundingBox | None, confidence: float | None = 0.9) -> OcrResult:
    return OcrResult(
        blocks=tuple(
            TextBlock(text=f"line {index}", box=box, confidence=confidence)
            for index, box in enumerate(boxes)
        )
    )


def test_boxes_are_mapped_back_into_source_space_after_a_resize(
    image_ref, tmp_path
):
    """`_StubPreprocessor` halves a 4x4 image to 2x2, so boxes double."""
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(
            _boxed(BoundingBox(x=1, y=1, width=1, height=1))
        ),
        preprocessor=_StubPreprocessor(tmp_path),
    ).run(image_ref)

    assert result.ocr.blocks[0].box.as_dict() == {
        "x": 2, "y": 2, "width": 2, "height": 2
    }
    assert result.metadata["bounding_box_space"] == "source"
    assert result.metadata["preprocessing_scale"] == [2.0, 2.0]


def test_a_field_inherits_the_corrected_box(image_ref, tmp_path):
    """Extraction runs after the mapping, so nothing downstream re-derives it."""

    class _BoxCopying(FieldExtractor):
        name, version = "box-copying", "0.0.0"

        def extract(self, ocr, image):
            return (
                ExtractedField(
                    key=LabelFieldKey.NET_QUANTITY,
                    raw_value=ocr.blocks[0].text,
                    box=ocr.blocks[0].box,
                ),
            )

    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(
            _boxed(BoundingBox(x=1, y=1, width=1, height=1))
        ),
        preprocessor=_StubPreprocessor(tmp_path),
        field_extractor=_BoxCopying(),
    ).run(image_ref)

    assert result.fields[0].box.as_dict() == {
        "x": 2, "y": 2, "width": 2, "height": 2
    }


def test_mapping_a_box_never_touches_its_confidence_or_text(image_ref, tmp_path):
    """Geometry is the only thing being corrected. Confidence is a measurement."""
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(
            _boxed(BoundingBox(x=1, y=1, width=1, height=1), confidence=0.42)
        ),
        preprocessor=_StubPreprocessor(tmp_path),
    ).run(image_ref)

    assert result.ocr.blocks[0].confidence == 0.42
    assert result.ocr.blocks[0].text == "line 0"


def test_a_block_without_a_box_survives_the_mapping(image_ref, tmp_path):
    """None means "the engine reported no geometry" and must stay None."""
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(_boxed(None)),
        preprocessor=_StubPreprocessor(tmp_path),
    ).run(image_ref)

    assert result.ocr.blocks[0].box is None


def test_nothing_is_moved_when_no_preprocessing_ran(image_ref):
    box = BoundingBox(x=1, y=1, width=2, height=2)
    result = ExtractionPipeline(
        name="stub", version="0.0.0", ocr_engine=_StubOcrEngine(_boxed(box)),
    ).run(image_ref)

    assert result.ocr.blocks[0].box == box
    assert result.metadata["bounding_box_space"] == "source"
    assert result.metadata["preprocessing_scale"] is None


def test_boxes_are_left_alone_when_the_scale_cannot_be_known(image_ref, tmp_path):
    """A preprocessor that does not report dimensions gets no guessed scale.

    Inventing one would move every box by a made-up factor while looking just
    as authoritative. Leaving them where the engine put them and saying so in
    metadata is the honest outcome.
    """

    class _Undimensioned(_StubPreprocessor):
        def process(self, image: ImageRef) -> ImageRef:
            processed = super().process(image)
            self.produced = ImageRef(
                path=processed.path, image_format="png",
                size_bytes=processed.size_bytes, width=None, height=None,
            )
            return self.produced

    box = BoundingBox(x=1, y=1, width=1, height=1)
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(_boxed(box)),
        preprocessor=_Undimensioned(tmp_path),
    ).run(image_ref)

    assert result.ocr.blocks[0].box == box
    assert result.metadata["bounding_box_space"] == "preprocessed"
    assert result.metadata["preprocessing_scale"] is None


def test_a_box_that_would_round_away_keeps_at_least_one_pixel(image_ref, tmp_path):
    """Scaling down must not delete a real detection.

    `BoundingBox` refuses a zero width, so an unguarded round() would raise on
    a thin box - losing the whole result over a rounding rule.
    """

    class _Enlarging(_StubPreprocessor):
        def process(self, image: ImageRef) -> ImageRef:
            processed = super().process(image)
            self.produced = ImageRef(
                path=processed.path, image_format="png",
                size_bytes=processed.size_bytes, width=400, height=400,
            )
            return self.produced

    # 400 -> 4 is a 0.01 scale: a 1px box would round to 0.
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(
            _boxed(BoundingBox(x=10, y=10, width=1, height=1))
        ),
        preprocessor=_Enlarging(tmp_path),
    ).run(image_ref)

    box = result.ocr.blocks[0].box
    assert box.width >= 1 and box.height >= 1


def test_a_mapped_box_stays_inside_the_source_image(image_ref, tmp_path):
    """A region outside the photograph cannot be shown to a reviewer."""

    class _Enlarging(_StubPreprocessor):
        def process(self, image: ImageRef) -> ImageRef:
            processed = super().process(image)
            self.produced = ImageRef(
                path=processed.path, image_format="png",
                size_bytes=processed.size_bytes, width=8, height=8,
            )
            return self.produced

    # The engine reports a box filling the 8x8 intermediate; the source is 4x4.
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(
            _boxed(BoundingBox(x=6, y=6, width=2, height=2))
        ),
        preprocessor=_Enlarging(tmp_path),
    ).run(image_ref)

    box = result.ocr.blocks[0].box
    assert box.x + box.width <= image_ref.width
    assert box.y + box.height <= image_ref.height


# --- declarations named on the label but not read ---------------------------


class _UnreadReporting(_StubFieldExtractor):
    """An extractor that reports one declaration it could not read."""

    def __init__(self, raises: Exception | None = None):
        self._raises = raises

    def unread_declarations(self, ocr, fields):
        if self._raises is not None:
            raise self._raises
        return (
            UnreadDeclaration(
                key=LabelFieldKey.RETAIL_SALE_PRICE,
                evidence_text="MRP",
                box=BoundingBox(x=1, y=1, width=2, height=2),
                confidence=0.93,
            ),
        )


def test_unread_declarations_reach_the_persisted_metadata(image_ref):
    """The backend stores `metadata` verbatim, so the signal survives a run.

    Without it, "the MRP keyword is printed here and we could not read it" and
    "this package declares no MRP" are the same empty `fields` tuple.
    """
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(OcrResult(blocks=(TextBlock(text="MRP"),))),
        field_extractor=_UnreadReporting(),
    ).run(image_ref)

    assert result.metadata["unread_declarations"] == [
        {
            "key": "retail_sale_price",
            "evidence_text": "MRP",
            "box": {"x": 1, "y": 1, "width": 2, "height": 2},
            "confidence": 0.93,
        }
    ]


def test_an_unread_declaration_never_becomes_an_extracted_field(image_ref):
    """It must not raise the field count, or a presence check would pass."""
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(OcrResult(blocks=(TextBlock(text="MRP"),))),
        field_extractor=_UnreadReporting(),
    ).run(image_ref)

    assert all(f.key is not LabelFieldKey.RETAIL_SALE_PRICE for f in result.fields)
    assert result.field_for(LabelFieldKey.RETAIL_SALE_PRICE) is None


def test_an_extractor_that_does_not_report_them_yields_an_empty_list(image_ref):
    """The hook is optional, and its absence reads as "nothing to report".

    The key is present on every run that got as far as extraction, so a
    consumer never has to distinguish "no unread declarations" from "this
    pipeline does not report them". A FAILED run carries no metadata at all -
    that is pre-existing and unchanged.
    """
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(OcrResult(blocks=(TextBlock(text="x"),))),
        field_extractor=_StubFieldExtractor(),
    ).run(image_ref)

    assert result.metadata["unread_declarations"] == []


def test_no_field_extractor_means_no_unread_declarations(image_ref):
    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(OcrResult(blocks=(TextBlock(text="MRP"),))),
    ).run(image_ref)

    assert result.metadata["unread_declarations"] == []


def test_an_unread_declaration_carries_a_source_space_box(image_ref, tmp_path):
    """The evidence box must point at the photograph, not the intermediate.

    An unread declaration exists to send a reviewer to look at a specific part
    of the package. `_StubPreprocessor` halves the image, so an unmapped box
    would be at half the coordinates and the reviewer would be shown the wrong
    region - with nothing failing to indicate it.

    The observation is built by the *real* extractor here rather than a stub,
    because what is being checked is that it reads its geometry from the
    already-rescaled `OcrResult` the pipeline hands it.
    """
    from labelextract.fields import RuleBasedFieldExtractor

    result = ExtractionPipeline(
        name="stub", version="0.0.0",
        ocr_engine=_StubOcrEngine(
            OcrResult(
                blocks=(
                    TextBlock(
                        text="MRP",
                        box=BoundingBox(x=1, y=1, width=1, height=1),
                        confidence=0.93,
                    ),
                )
            )
        ),
        preprocessor=_StubPreprocessor(tmp_path),
        field_extractor=RuleBasedFieldExtractor(),
    ).run(image_ref)

    [observation] = result.metadata["unread_declarations"]
    assert observation["key"] == "retail_sale_price"
    # Doubled from the 2x2 intermediate back into the 4x4 source.
    assert observation["box"] == {"x": 2, "y": 2, "width": 2, "height": 2}
    assert observation["confidence"] == 0.93


def test_an_extractor_without_the_optional_hook_is_not_treated_as_broken(
    image_ref, caplog
):
    """"Not implemented" and "implemented and broken" are different.

    An extractor that does not subclass `FieldExtractor` is out of contract but
    functional. Logging a traceback for it on every image would bury the case
    that genuinely needs attention.
    """

    class _DuckTyped:
        name, version, is_placeholder = "duck", "0.0.0", False

        def warmup(self):
            pass

        def extract(self, ocr, image):
            return ()

    with caplog.at_level(logging.WARNING):
        result = ExtractionPipeline(
            name="stub", version="0.0.0",
            ocr_engine=_StubOcrEngine(OcrResult(blocks=(TextBlock(text="MRP"),))),
            field_extractor=_DuckTyped(),
        ).run(image_ref)

    assert result.metadata["unread_declarations"] == []
    assert caplog.text == ""


def test_a_failure_reporting_them_does_not_cost_the_extracted_fields(
    image_ref, caplog
):
    """A footnote about a result must not be able to destroy the result.

    Same rule as `release()`: this is a secondary observation about work that
    already succeeded, so a bug in it costs the observation and a log line.
    """
    with caplog.at_level(logging.WARNING):
        result = ExtractionPipeline(
            name="stub", version="0.0.0",
            ocr_engine=_StubOcrEngine(OcrResult(blocks=(TextBlock(text="x"),))),
            field_extractor=_UnreadReporting(raises=RuntimeError("boom")),
        ).run(image_ref)

    assert result.status is ExtractionStatus.COMPLETED
    assert len(result.fields) == 1
    assert result.metadata["unread_declarations"] == []
    assert "unread declarations" in caplog.text


# --- cleanup must never overrule the outcome it is cleaning up after --------


class _HostilePreprocessor(_StubPreprocessor):
    """A preprocessor whose `release` raises, in breach of its own contract.

    `ImagePreprocessor.release` is documented as never raising. This stands in
    for the implementation that gets it wrong - a future engine, or a
    third-party one - and pins down what that costs: a log line, not a result.
    """

    def release(self, processed: ImageRef) -> None:
        self.released.append(processed)
        raise RuntimeError("cleanup exploded")


def test_a_failing_release_does_not_turn_a_success_into_a_crash(image_ref, tmp_path):
    """`release` is called from a `finally`, so an escape would replace the return.

    The extraction was already complete and correct at that point; losing it to
    a temporary-file problem would be the worst possible trade.
    """
    preprocessor = _HostilePreprocessor(tmp_path)
    result = ExtractionPipeline(
        name="stub",
        version="0.0.0",
        ocr_engine=_StubOcrEngine(OcrResult(blocks=(TextBlock(text="Net Qty 500 g"),))),
        preprocessor=preprocessor,
        field_extractor=_StubFieldExtractor(),
    ).run(image_ref)

    assert result.status is ExtractionStatus.COMPLETED
    assert result.field_for(LabelFieldKey.NET_QUANTITY).raw_value == "500 g"
    # It really did try, and really did raise.
    assert len(preprocessor.released) == 1


def test_a_failing_release_does_not_mask_a_recorded_extraction_failure(
    image_ref, tmp_path
):
    """The `error_code` explaining the real problem must still reach the caller.

    An exception from `finally` would discard the `return` mid-flight, so the
    operator would be told about a temporary file instead of about the
    unreadable image.
    """
    result = ExtractionPipeline(
        name="stub",
        version="0.0.0",
        ocr_engine=_StubOcrEngine(raises=InvalidImageError("unreadable")),
        preprocessor=_HostilePreprocessor(tmp_path),
    ).run(image_ref)

    assert result.status is ExtractionStatus.FAILED
    assert result.error_code == "invalid_image"


def test_a_failing_release_does_not_mask_a_bug_in_an_engine(image_ref, tmp_path):
    """The loud failure stays loud, and stays the *original* failure.

    An engine bug must still surface as itself rather than as `RuntimeError:
    cleanup exploded`, which would send whoever debugs it to the wrong file.
    """
    pipeline = ExtractionPipeline(
        name="stub",
        version="0.0.0",
        ocr_engine=_StubOcrEngine(raises=ZeroDivisionError("bug in engine")),
        preprocessor=_HostilePreprocessor(tmp_path),
    )

    with pytest.raises(ZeroDivisionError):
        pipeline.run(image_ref)


def test_a_failing_release_is_logged_rather_than_silently_dropped(
    image_ref, tmp_path, caplog
):
    """Swallowed exceptions have to leave a trace, or the bug is undiscoverable."""
    with caplog.at_level(logging.WARNING, logger="labelextract.pipeline"):
        ExtractionPipeline(
            name="stub",
            version="0.0.0",
            ocr_engine=_StubOcrEngine(),
            preprocessor=_HostilePreprocessor(tmp_path),
        ).run(image_ref)

    assert any(
        "failed to release" in record.message for record in caplog.records
    )
