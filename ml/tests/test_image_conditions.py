"""The pipeline under the photograph conditions a real label arrives in.

Small print, low contrast, text at an angle, a frame with nothing readable in
it, a file that is not an image at all, a preprocessor that fails, a missing
binary. Each of these is a thing a person will actually upload, and each has a
*defined* outcome this package promises.

**What these tests assert is behaviour, never recognition quality.** Not one of
them requires a particular string to come back. That is deliberate and it is
the same rule the Tesseract smoke test follows: an assertion like "'500' must
be recognised" is an accuracy claim dressed as a test, it breaks when a font or
a Tesseract version changes, and no number from it could honestly be reported.
Accuracy is measured against an annotated set, per docs/evaluation-strategy.md,
and has not been measured.

What is worth pinning here instead:

- an unreadable photograph is `EMPTY`, never `FAILED` and never a fabricated
  reading - the difference between "retake the photo" and "your package is
  illegal";
- a broken input is `FAILED` with a stable `error_code`;
- confidence survives every path, and stays absent rather than invented;
- **every box lands inside the source photograph**, whatever the preprocessor
  did to the pixels on the way. Upscaling is on for the Tesseract pipeline, so
  this is the regression that would otherwise put an evidence overlay in the
  wrong place with nothing failing.

The synthetic images are rendered here rather than committed. No product
photograph is in this repository (see ml/data/README.md), and a test that
needed one could not run on a fresh clone.
"""

from __future__ import annotations

import pytest

from labelextract import registry
from labelextract.contracts import ExtractionStatus, ImageRef
from labelextract.exceptions import EngineNotAvailableError, PreprocessingError
from labelextract.fields import SUPPORTED_KEYS, RuleBasedFieldExtractor
from labelextract.ocr import tesseract
from labelextract.ocr.tesseract import TesseractOcrEngine, TesseractOptions
from labelextract.pipeline import ExtractionPipeline
from labelextract.preprocessing import PillowPreprocessor, PreprocessingConfig

PIL = pytest.importorskip("PIL", reason="Pillow is part of the optional [ocr] extra")

from PIL import Image, ImageDraw  # noqa: E402  - after the skip guard on purpose

DECLARATION_LINES = [
    "NET QUANTITY : 120 GRAMS",
    "MRP : 349.00 INCL. OF ALL TAXES",
    "BATCH : 2546",
    "BEST BEFORE 2 YEARS FROM MFG. DT.",
]


def _write(image: Image.Image, path) -> ImageRef:
    image.save(path, format="PNG")
    return ImageRef(
        path=path,
        image_format="png",
        size_bytes=path.stat().st_size,
        width=image.width,
        height=image.height,
    )


@pytest.fixture
def label(tmp_path):
    """Render a label-like image under a named condition.

    Sizes and greys are chosen to *resemble* the conditions, not to reproduce
    any real photograph. Nothing here is evaluation data.
    """

    def _make(condition: str = "normal") -> ImageRef:
        if condition == "unreadable":
            # A flat frame with no glyphs at all: the blurred or blank photo.
            image = Image.new("RGB", (400, 300), (140, 140, 140))
            return _write(image, tmp_path / "unreadable.png")

        size = (760, 260)
        background, ink = (250, 248, 240), (10, 10, 10)
        spacing, origin = 44, 24

        if condition == "low_contrast":
            background, ink = (138, 136, 130), (116, 114, 108)
        if condition == "small_text":
            size, spacing, origin = (300, 110), 16, 8

        image = Image.new("RGB", size, background)
        draw = ImageDraw.Draw(image)
        for index, line in enumerate(DECLARATION_LINES):
            draw.text((origin, origin + index * spacing), line, fill=ink)

        if condition == "angled":
            # Rotated with expansion, so the text is skewed and the corners are
            # background - a hand-held photograph, roughly.
            image = image.rotate(12, expand=True, fillcolor=background)

        return _write(image, tmp_path / f"{condition}.png")

    return _make


def _tesseract_or_skip():
    """The current pipeline, skipped when the binary is not installed.

    Same rule as the OCR smoke test: the suite must pass on a fresh clone with
    no OCR stack, so anything that shells out is opt-in on the environment.
    """
    pytest.importorskip("pytesseract")
    pipeline = registry.get_pipeline(tesseract.NAME, tesseract.VERSION)
    try:
        pipeline.ocr_engine.warmup()
    except EngineNotAvailableError:
        pytest.skip("the tesseract binary is not installed on this machine")
    return pipeline


def _assert_result_is_well_formed(result, image: ImageRef) -> None:
    """Every promise the contract makes about a completed run, in one place."""
    assert result.status in (ExtractionStatus.COMPLETED, ExtractionStatus.EMPTY)
    assert result.error_code is None
    assert result.is_placeholder is False

    for block in result.ocr.blocks:
        if block.confidence is not None:
            assert 0.0 <= block.confidence <= 1.0
        if block.box is not None:
            assert block.box.x >= 0 and block.box.y >= 0
            assert block.box.x + block.box.width <= image.width
            assert block.box.y + block.box.height <= image.height

    for extracted in result.fields:
        if extracted.box is not None:
            assert extracted.box.x + extracted.box.width <= image.width
            assert extracted.box.y + extracted.box.height <= image.height


# --- photograph conditions --------------------------------------------------


@pytest.mark.parametrize(
    "condition", ["normal", "small_text", "low_contrast", "angled"]
)
def test_a_readable_condition_produces_a_well_formed_result(label, condition):
    """No claim about *what* was read - only that the contract holds.

    `small_text` is the case the upscaling exists for and `angled` is the one
    nothing here corrects, so both are expected to differ wildly in quality.
    Quality is not what is being asserted.
    """
    image = label(condition)
    _assert_result_is_well_formed(_tesseract_or_skip().run(image), image)


def test_boxes_stay_inside_the_photograph_when_preprocessing_upscaled_it(label):
    """The regression the box mapping exists to prevent, end to end.

    The pipeline upscales a small image before recognition, so the engine
    reports boxes in a coordinate system twice the size of the file the user
    uploaded. If the mapping back were dropped, boxes would still be perfectly
    valid - just describing the wrong half of the package.
    """
    image = label("small_text")
    result = _tesseract_or_skip().run(image)

    assert result.metadata["bounding_box_space"] == "source"
    scale = result.metadata["preprocessing_scale"]
    assert scale is not None and scale[0] < 1.0, (
        "the small image should have been upscaled, so mapping back shrinks"
    )
    boxed = [b for b in result.ocr.blocks if b.box is not None]
    if boxed:  # recognition may legitimately return nothing
        for block in boxed:
            assert block.box.x + block.box.width <= image.width
            assert block.box.y + block.box.height <= image.height


def test_an_unreadable_photograph_is_empty_rather_than_failed(label):
    """`EMPTY` means "we looked and found nothing usable", which is not an error.

    Reporting it as FAILED would send a user to fix a system problem, and
    reporting a missing declaration would be a compliance claim about a
    photograph nobody could read.
    """
    image = label("unreadable")
    result = _tesseract_or_skip().run(image)

    assert result.status is ExtractionStatus.EMPTY
    assert result.fields == ()
    assert result.error_code is None


def test_field_extraction_still_receives_what_it_expects(label):
    """The preprocessing change must not alter the extractor's input contract.

    Whatever is or is not extracted, an `ExtractedField` must remain a
    well-formed observation: a key from the vocabulary, the raw reading kept
    verbatim, and confidence either measured or absent.
    """
    result = _tesseract_or_skip().run(label("normal"))

    for extracted in result.fields:
        assert extracted.key in SUPPORTED_KEYS
        assert isinstance(extracted.raw_value, str) and extracted.raw_value
        if extracted.confidence is not None:
            assert 0.0 <= extracted.confidence <= 1.0
        if extracted.normalized_value is not None:
            assert "uncertain" in extracted.normalized_value


# --- broken inputs, which need no binary at all -----------------------------


def test_an_empty_file_is_a_recorded_failure(tmp_path):
    path = tmp_path / "empty.png"
    path.write_bytes(b"")
    image = ImageRef(path=path, image_format="png", size_bytes=0)

    result = registry.get_pipeline(tesseract.NAME, tesseract.VERSION).run(image)

    assert result.status is ExtractionStatus.FAILED
    assert result.error_code == "invalid_image"


def test_a_file_that_is_not_an_image_is_a_recorded_failure(tmp_path):
    path = tmp_path / "notanimage.png"
    path.write_text("BEST BEFORE 2 YEARS FROM MFG. DT.", encoding="utf-8")
    image = ImageRef(
        path=path, image_format="png", size_bytes=path.stat().st_size
    )

    result = registry.get_pipeline(tesseract.NAME, tesseract.VERSION).run(image)

    assert result.status is ExtractionStatus.FAILED
    assert result.error_code == "invalid_image"


def test_a_preprocessing_failure_is_recorded_and_never_reaches_the_engine(label):
    """Our storage failing is not the user's photograph failing."""

    class _Failing(PillowPreprocessor):
        def process(self, image: ImageRef) -> ImageRef:
            raise PreprocessingError("the intermediate could not be written")

    class _Unreachable(TesseractOcrEngine):
        def recognise(self, image: ImageRef):  # pragma: no cover - must not run
            raise AssertionError("recognition ran after preprocessing failed")

    result = ExtractionPipeline(
        name=tesseract.NAME, version=tesseract.VERSION,
        ocr_engine=_Unreachable(),
        preprocessor=_Failing(),
        field_extractor=RuleBasedFieldExtractor(),
    ).run(label("normal"))

    assert result.status is ExtractionStatus.FAILED
    assert result.error_code == "preprocessing_failed"


def test_a_missing_ocr_binary_is_an_actionable_failed_run(label):
    """Not a crash, and not an empty reading that looks like a blank label."""

    class _Missing(tesseract.TesseractRunner):
        def version(self):
            raise EngineNotAvailableError("The tesseract binary was not found.")

        def word_data(self, path, options):
            raise EngineNotAvailableError("The tesseract binary was not found.")

    result = ExtractionPipeline(
        name=tesseract.NAME, version=tesseract.VERSION,
        ocr_engine=TesseractOcrEngine(TesseractOptions(), runner=_Missing()),
        preprocessor=PillowPreprocessor(
            PreprocessingConfig(min_dimension=None)
        ),
        field_extractor=RuleBasedFieldExtractor(),
    ).run(label("normal"))

    assert result.status is ExtractionStatus.FAILED
    assert result.error_code == "engine_not_available"
    assert result.fields == ()
