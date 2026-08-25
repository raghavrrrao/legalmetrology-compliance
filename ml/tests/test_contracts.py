from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

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


def test_image_ref_rejects_string_path():
    with pytest.raises(TypeError):
        ImageRef(path="not-a-path", image_format="png", size_bytes=10)


def test_image_ref_allows_unknown_dimensions(png_path: Path):
    """Metadata we could not probe stays None rather than being guessed."""
    ref = ImageRef(path=png_path, image_format="jpeg", size_bytes=100)
    assert ref.width is None
    assert ref.height is None


@pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0])
def test_text_block_confidence_must_be_a_probability(bad):
    with pytest.raises(ValueError):
        TextBlock(text="MRP", confidence=bad)


def test_text_block_confidence_may_be_absent():
    """Engines that report no confidence must not have one invented for them."""
    assert TextBlock(text="MRP").confidence is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"x": 0, "y": 0, "width": 0, "height": 5},
        {"x": 0, "y": 0, "width": 5, "height": -1},
        {"x": -1, "y": 0, "width": 5, "height": 5},
    ],
)
def test_bounding_box_rejects_impossible_geometry(kwargs):
    with pytest.raises(ValueError):
        BoundingBox(**kwargs)


def test_bounding_box_as_dict_is_json_ready():
    box = BoundingBox(x=1, y=2, width=3, height=4)
    assert box.as_dict() == {"x": 1, "y": 2, "width": 3, "height": 4}


def test_extracted_field_requires_a_raw_value():
    """An empty reading is not an observation and must not be recorded as one."""
    with pytest.raises(ValueError):
        ExtractedField(key=LabelFieldKey.NET_QUANTITY, raw_value="")


def test_ocr_result_full_text_joins_blocks_in_order():
    ocr = OcrResult(
        blocks=(TextBlock(text="Net Qty 500 g"), TextBlock(text="MRP Rs. 250"))
    )
    assert ocr.full_text == "Net Qty 500 g\nMRP Rs. 250"


def test_ocr_result_defaults_to_empty():
    ocr = OcrResult()
    assert ocr.blocks == ()
    assert ocr.full_text == ""


def test_field_for_returns_none_when_absent():
    result = ExtractionResult(
        status=ExtractionStatus.COMPLETED,
        engine_name="stub",
        engine_version="0.0.0",
        processing_ms=1,
        fields=(
            ExtractedField(key=LabelFieldKey.NET_QUANTITY, raw_value="500 g"),
        ),
    )
    assert result.field_for(LabelFieldKey.NET_QUANTITY).raw_value == "500 g"
    assert result.field_for(LabelFieldKey.RETAIL_SALE_PRICE) is None


def test_results_are_immutable():
    """Extraction output is an audit record and must not be edited in place.

    Asserts the specific FrozenInstanceError rather than bare Exception: a
    broad catch would also pass if the test itself raised AttributeError or
    NameError, which would make this look like it verifies immutability when
    it verifies nothing.
    """
    field = ExtractedField(key=LabelFieldKey.NET_QUANTITY, raw_value="500 g")
    with pytest.raises(FrozenInstanceError):
        field.raw_value = "1 kg"  # type: ignore[misc]
