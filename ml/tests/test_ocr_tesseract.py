"""The Tesseract adapter, tested without Tesseract.

Everything worth testing in this module is *ours*: grouping words into lines,
rescaling confidence, refusing to invent one, mapping engine failures onto the
right exception. All of that is exercised through a deterministic fake runner,
so the suite runs on a fresh clone, in CI, and offline - which is a hard
requirement, not a convenience. There is exactly one test that needs the real
binary, and it skips when it is absent.
"""

from pathlib import Path

import pytest

from labelextract.contracts import ImageRef, OcrResult
from labelextract.exceptions import (
    EngineNotAvailableError,
    InvalidImageError,
    OcrFailureError,
)
from labelextract.ocr.tesseract import (
    NAME,
    VERSION,
    TesseractOcrEngine,
    TesseractOptions,
    TesseractRunner,
)


class FakeRunner(TesseractRunner):
    """A Tesseract that says whatever the test needs it to say."""

    def __init__(self, data=None, *, raises: Exception | None = None,
                 version: str | None = "5.3.4"):
        self._data = data if data is not None else {"text": []}
        self._raises = raises
        self._version = version
        self.calls: list[tuple[Path, TesseractOptions]] = []

    def version(self) -> str | None:
        return self._version

    def word_data(self, path, options):
        self.calls.append((path, options))
        if self._raises is not None:
            raise self._raises
        return self._data


@pytest.fixture
def engine_for(png_path):
    def _make(runner: TesseractRunner) -> TesseractOcrEngine:
        return TesseractOcrEngine(runner=runner)

    return _make


# --- a valid image reaches OCR ----------------------------------------------


def test_a_valid_image_is_handed_to_the_engine(image_ref, engine_for, tesseract_data):
    runner = FakeRunner(tesseract_data([("Net Qty 500 g", 92)]))
    engine_for(runner).recognise(image_ref)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == image_ref.path.resolve()


def test_words_are_grouped_into_lines(image_ref, engine_for, tesseract_data):
    """Field extraction reasons about lines, so the engine reports lines."""
    runner = FakeRunner(
        tesseract_data([("Net Qty 500 g", 92), ("MRP Rs. 250", 88)])
    )
    result = engine_for(runner).recognise(image_ref)

    assert [block.text for block in result.blocks] == [
        "Net Qty 500 g",
        "MRP Rs. 250",
    ]
    assert result.full_text == "Net Qty 500 g\nMRP Rs. 250"


def test_a_line_carries_a_box_spanning_all_of_its_words(
    image_ref, engine_for, tesseract_data
):
    """Without geometry the UI cannot show where a declaration was read."""
    runner = FakeRunner(tesseract_data([("Net Qty 500 g", 92)]))
    block = engine_for(runner).recognise(image_ref).blocks[0]

    assert block.box is not None
    # Four words at x = 10, 70, 130, 190, each 55 wide.
    assert block.box.x == 10
    assert block.box.width == 235


def test_confidence_is_rescaled_from_tesseracts_percentage(
    image_ref, engine_for, tesseract_data
):
    runner = FakeRunner(tesseract_data([("Net Qty", 92)]))
    block = engine_for(runner).recognise(image_ref).blocks[0]

    assert block.confidence == pytest.approx(0.92)


def test_an_unreported_confidence_stays_none_rather_than_becoming_zero(
    image_ref, engine_for, tesseract_data
):
    """None means 'not reported'. Zero would mean 'certainly wrong'.

    A fabricated number here would propagate into a compliance result and make
    a guess look like a measurement.
    """
    data = tesseract_data([("Net Qty", 92)])
    data["conf"] = [-1] * len(data["conf"])
    runner = FakeRunner(data)

    block = engine_for(runner).recognise(image_ref).blocks[0]
    assert block.confidence is None


def test_word_level_detail_is_kept_for_re_running_extraction(
    image_ref, engine_for, tesseract_data
):
    """So a better extractor can be run over an old result without new OCR."""
    runner = FakeRunner(tesseract_data([("Net Qty 500 g", 92)]))
    result = engine_for(runner).recognise(image_ref)

    assert result.raw["word_count"] == 4
    assert result.raw["line_count"] == 1
    assert result.raw["tesseract_version"] == "5.3.4"
    assert [word["text"] for word in result.raw["words"]] == [
        "Net", "Qty", "500", "g",
    ]


def test_low_confidence_words_are_kept_by_default(
    image_ref, engine_for, tesseract_data
):
    """Discarding them hides exactly the misreadings a reviewer must see."""
    runner = FakeRunner(tesseract_data([("Nel Oty 5OO g", 12)]))
    result = engine_for(runner).recognise(image_ref)

    assert result.blocks[0].text == "Nel Oty 5OO g"
    assert result.blocks[0].confidence == pytest.approx(0.12)


def test_a_confidence_floor_can_be_set_explicitly(image_ref, tesseract_data):
    engine = TesseractOcrEngine(
        TesseractOptions(minimum_word_confidence=50),
        runner=FakeRunner(tesseract_data([("Nel Oty", 12)])),
    )
    assert engine.recognise(image_ref).blocks == ()


# --- empty output -----------------------------------------------------------


def test_no_recognised_text_is_an_empty_result_not_an_error(
    image_ref, engine_for
):
    """A blurred or blank photograph is a legitimate outcome.

    The pipeline turns this into `ExtractionStatus.EMPTY`, which the compliance
    engine treats as inconclusive rather than as a missing declaration - the
    difference between "retake the photo" and "your package is illegal".
    """
    result = engine_for(FakeRunner({"text": []})).recognise(image_ref)

    assert isinstance(result, OcrResult)
    assert result.blocks == ()
    assert result.full_text == ""


def test_whitespace_only_words_are_discarded(image_ref, engine_for, tesseract_data):
    data = tesseract_data([("Net Qty", 90)])
    data["text"] = ["   " for _ in data["text"]]
    assert engine_for(FakeRunner(data)).recognise(image_ref).blocks == ()


# --- failures ---------------------------------------------------------------


def test_a_missing_file_is_an_invalid_image(engine_for, tmp_path):
    ref = ImageRef(path=tmp_path / "gone.png", image_format="png", size_bytes=5)
    with pytest.raises(InvalidImageError):
        engine_for(FakeRunner()).recognise(ref)


def test_an_empty_file_is_an_invalid_image(engine_for, tmp_path):
    path = tmp_path / "empty.png"
    path.write_bytes(b"")
    ref = ImageRef(path=path, image_format="png", size_bytes=0)

    with pytest.raises(InvalidImageError):
        engine_for(FakeRunner()).recognise(ref)


def test_a_missing_binary_is_reported_as_an_unavailable_engine(
    image_ref, engine_for
):
    """Actionable for an operator: install Tesseract. Not "your image is bad"."""
    runner = FakeRunner(raises=EngineNotAvailableError("tesseract not on PATH"))
    with pytest.raises(EngineNotAvailableError):
        engine_for(runner).recognise(image_ref)


def test_an_engine_crash_is_an_ocr_failure(image_ref, engine_for):
    runner = FakeRunner(raises=OcrFailureError("tesseract timed out"))
    with pytest.raises(OcrFailureError):
        engine_for(runner).recognise(image_ref)


def test_unparseable_engine_output_is_an_ocr_failure(image_ref, engine_for):
    """The engine ran and produced something we cannot read.

    Not a bug in our code, and emphatically not "the package had no text on
    it" - so it must not become an EMPTY result.
    """
    runner = FakeRunner({"not_the_expected": "shape"})
    with pytest.raises(OcrFailureError):
        engine_for(runner).recognise(image_ref)


def test_warmup_surfaces_a_missing_engine_before_the_first_upload(engine_for):
    class Unavailable(FakeRunner):
        def version(self):
            raise EngineNotAvailableError("tesseract not on PATH")

    with pytest.raises(EngineNotAvailableError):
        engine_for(Unavailable()).warmup()


@pytest.mark.parametrize(
    ("failure", "expectation"),
    [
        ("missing-binary", "raises"),
        ("unreadable-version", "returns-none"),
    ],
)
def test_a_missing_binary_and_an_unreadable_version_are_different_outcomes(
    failure, expectation
):
    """`warmup()` must fail loudly on the first and shrug at the second.

    Collapsing them would make `warmup()` do nothing about the one failure it
    exists to catch: a missing binary would then resurface as a failed run on a
    user's first upload instead of at startup. Not being able to parse a
    version banner, by contrast, only costs an entry in the audit trail and is
    no reason to refuse a run the engine can complete.
    """
    pytesseract = pytest.importorskip("pytesseract")

    from labelextract.ocr.tesseract import PytesseractRunner

    class _FakeModule:
        """Stands in for the pytesseract module, raising on demand."""

        TesseractNotFoundError = pytesseract.TesseractNotFoundError

        def get_tesseract_version(self):
            if failure == "missing-binary":
                raise self.TesseractNotFoundError()
            raise ValueError("could not parse the version banner")

    class _Runner(PytesseractRunner):
        def _pytesseract(self):
            return _FakeModule()

    if expectation == "raises":
        with pytest.raises(EngineNotAvailableError):
            _Runner().version()
    else:
        assert _Runner().version() is None


# --- options are a security boundary ----------------------------------------


@pytest.mark.parametrize(
    "languages",
    [
        (),
        ("eng; rm -rf /",),
        ("../../etc/passwd",),
        ("e",),
        ("eng hin",),
    ],
)
def test_language_codes_are_validated_before_they_reach_a_subprocess(languages):
    """The language becomes a command-line argument. Nothing else may.

    pytesseract does not use a shell, so this is defence in depth - but the
    setting is the one value here that could plausibly become user-supplied.
    """
    with pytest.raises(ValueError):
        TesseractOptions(languages=languages)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page_segmentation_mode": 99},
        {"engine_mode": -1},
        {"timeout_seconds": 0},
        {"minimum_word_confidence": 101},
    ],
)
def test_out_of_range_options_are_rejected(kwargs):
    with pytest.raises(ValueError):
        TesseractOptions(**kwargs)


def test_the_config_argument_is_built_only_from_validated_integers():
    assert (
        TesseractOptions(page_segmentation_mode=6, engine_mode=3).config_argument
        == "--psm 6 --oem 3"
    )


def test_the_default_page_segmentation_mode_is_the_one_that_was_measured():
    """3 (automatic segmentation), not 6 (one uniform block).

    6 assumes the frame is already a cropped panel. People photograph a product
    on a desk, and 6 then lets the desk take part in the line structure. The
    modes were compared on the Product 001 set rather than reasoned about; see
    the `page_segmentation_mode` docstring and ml/README.md.

    Pinned because it is a default that silently changes results: nothing
    fails, the numbers just get worse.
    """
    assert TesseractOptions().page_segmentation_mode == 3
    assert TesseractOptions().config_argument == "--psm 3 --oem 3"


def test_the_frozen_baseline_keeps_its_own_settings_whatever_the_defaults_do():
    """0.1.0 exists to be compared against, so it must not drift with them."""
    from labelextract.ocr import tesseract

    baseline = tesseract.build_baseline_pipeline()

    assert baseline.version == tesseract.BASELINE_VERSION == "0.1.0"
    assert baseline.ocr_engine.options.page_segmentation_mode == 6


def test_multiple_languages_are_joined_the_way_tesseract_expects():
    assert TesseractOptions(languages=("eng", "hin")).language_argument == "eng+hin"


# --- the one test that needs the real thing ---------------------------------


def test_the_real_engine_round_trips_through_the_binary(tmp_path):
    """An integration check against the actual binary, skipped when absent.

    What it asserts is that the *integration works*: the subprocess is found
    and executed, its TSV output comes back, our parser consumes it without
    raising, and the result is a well-formed `OcrResult`. That is what breaks
    when a Tesseract upgrade changes its output columns, when the timeout
    plumbing regresses, or when a language argument stops being accepted - and
    all of it is our code's responsibility.

    It deliberately asserts **nothing about what Tesseract read.** An earlier
    version rendered text in Pillow's 11-pixel default bitmap font and required
    "500" to come back, which is a claim about recognition accuracy dressed up
    as a smoke test: it would fail on a font change, and no number from it
    could honestly be reported anywhere. Recognition quality is measured
    against an annotated set, per docs/evaluation-strategy.md, and has not been
    measured at all.
    """
    pytest.importorskip("pytesseract")
    pytest.importorskip("PIL")

    from PIL import Image, ImageDraw

    from labelextract.ocr.tesseract import PytesseractRunner

    runner = PytesseractRunner()
    try:
        version = runner.version()
    except EngineNotAvailableError:
        pytest.skip("the tesseract binary is not installed on this machine")
    if version is None:
        pytest.skip("Tesseract did not report a usable version")

    path = tmp_path / "rendered.png"
    image = Image.new("RGB", (420, 90), (255, 255, 255))
    ImageDraw.Draw(image).text((12, 30), "NET QTY 500 g", fill=(0, 0, 0))
    image.save(path)

    result = TesseractOcrEngine().recognise(
        ImageRef(
            path=path,
            image_format="png",
            size_bytes=path.stat().st_size,
            width=420,
            height=90,
        )
    )

    # The binary ran and its output was parsed into our contract.
    assert isinstance(result, OcrResult)
    assert result.raw["tesseract_version"] == version
    assert result.raw["languages"] == ["eng"]
    assert isinstance(result.raw["words"], list)
    assert result.raw["line_count"] == len(result.blocks)
    # Whatever it recognised - including nothing - is structurally valid.
    for block in result.blocks:
        assert block.text.strip()
        assert block.confidence is None or 0.0 <= block.confidence <= 1.0


def test_the_engine_identifies_itself_for_the_audit_trail():
    engine = TesseractOcrEngine(runner=FakeRunner())
    assert engine.name == NAME
    assert engine.version == VERSION
    assert engine.is_placeholder is False


# --- pytesseract's exceptions subclass builtins, so clause order is load-bearing


def _runner_raising(exception):
    """A `PytesseractRunner` whose `image_to_data` raises `exception`.

    Only the pytesseract module is faked. `word_data`'s real body runs - the
    Pillow open, the call, and above all the `except` ladder under test.
    """
    pytesseract = pytest.importorskip("pytesseract")

    from labelextract.ocr.tesseract import PytesseractRunner

    class _Module:
        TesseractError = pytesseract.TesseractError
        TesseractNotFoundError = pytesseract.TesseractNotFoundError

        class Output:
            DICT = "dict"

        @staticmethod
        def image_to_data(*args, **kwargs):
            raise exception

    class _Runner(PytesseractRunner):
        def _pytesseract(self):
            return _Module()

    return _Runner()


def test_a_tesseract_processing_error_is_not_reported_as_a_timeout(png_path):
    """`TesseractError` subclasses `RuntimeError`, so ordering decides the message.

    With the broader `except RuntimeError` placed first, this clause was
    unreachable and every genuine engine error was recorded as "timed out or
    aborted" - sending whoever reads `ExtractionRun.error_message` to look at
    the wrong thing.
    """
    pytest.importorskip("PIL")
    pytesseract = pytest.importorskip("pytesseract")

    runner = _runner_raising(
        pytesseract.TesseractError(1, "Error in pixReadStream: Unknown format")
    )

    with pytest.raises(OcrFailureError) as raised:
        runner.word_data(png_path, TesseractOptions())

    message = str(raised.value)
    assert "pixReadStream" in message
    assert "timed out" not in message


def test_a_timeout_is_still_reported_as_a_timeout(png_path):
    """The contrast that makes the assertion above mean something."""
    pytest.importorskip("PIL")
    pytest.importorskip("pytesseract")

    runner = _runner_raising(RuntimeError("Tesseract process timeout, timeout=30"))

    with pytest.raises(OcrFailureError) as raised:
        runner.word_data(png_path, TesseractOptions())

    assert "timed out" in str(raised.value)


def test_a_missing_binary_is_still_an_unavailable_engine_not_a_bad_image(png_path):
    """`TesseractNotFoundError` subclasses `OSError`, so it must precede it.

    Otherwise "install Tesseract" is reported to the user as "your image could
    not be decoded".
    """
    pytest.importorskip("PIL")
    pytesseract = pytest.importorskip("pytesseract")

    runner = _runner_raising(pytesseract.TesseractNotFoundError())

    with pytest.raises(EngineNotAvailableError):
        runner.word_data(png_path, TesseractOptions())
