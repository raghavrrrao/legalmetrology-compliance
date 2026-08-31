"""The empty-result page-segmentation retry.

Mode 3 does not degrade gracefully. On a photograph whose layout it cannot
resolve it returns zero words rather than a poor reading, and the pipeline
reports EMPTY - which tells a reviewer nothing except "take another photo".
Measured on the 28 photographs of `our-eval-v0.3-usp-partial`, that happened on
two of them, and modes 6, 11 and 12 each read text on both.

Everything here runs against the deterministic fake runner, because what is
worth testing is *ours*: when a second pass is attempted, which result is kept,
and what the run records about it. See `docs/evaluation-results.md` for the
measurement that chose mode 11 over mode 6.
"""

from pathlib import Path

import pytest

from labelextract.contracts import ExtractionStatus
from labelextract.exceptions import (
    EngineNotAvailableError,
    InvalidImageError,
    OcrFailureError,
)
from labelextract.ocr.tesseract import (
    TesseractOcrEngine,
    TesseractOptions,
    TesseractRunner,
)


class ScriptedRunner(TesseractRunner):
    """Returns different word data depending on the page-segmentation mode.

    A real second pass differs from the first only in the `--psm` it was given,
    so that is exactly what this keys on. Every call is recorded, which is how
    the "did it run twice?" assertions below can be made at all.

    A mapped value may be an exception instance instead of word data, which is
    how a pass that *fails* is scripted. Real Tesseract fails per call - a
    timeout on one segmentation mode says nothing about another - so failure
    has to be per mode here too.
    """

    def __init__(self, by_mode: dict[int, object], *, version: str | None = "5.4.0"):
        self._by_mode = by_mode
        self._version = version
        self.calls: list[tuple[Path, TesseractOptions]] = []

    def version(self) -> str | None:
        return self._version

    def word_data(self, path, options):
        self.calls.append((path, options))
        outcome = self._by_mode.get(options.page_segmentation_mode, {"text": []})
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def modes_run(self) -> list[int]:
        return [options.page_segmentation_mode for _, options in self.calls]


@pytest.fixture
def nothing(tesseract_data):
    return tesseract_data([])


# --- the option -------------------------------------------------------------


def test_the_default_fallback_mode_is_the_one_that_was_measured():
    """11, not 6.

    Mode 6 recovers more characters on the two images that need a retry and was
    rejected for it: the extra text it finds includes a line the price detector
    reads as a retail sale price of 4, on a panel whose price a human could not
    read. Mode 11 recovered 876 characters and changed no scored outcome.

    Pinned because it is a default that silently changes results.
    """
    assert TesseractOptions().fallback_page_segmentation_mode == 11
    assert TesseractOptions().page_segmentation_mode == 3


def test_an_out_of_range_fallback_mode_is_rejected():
    with pytest.raises(ValueError):
        TesseractOptions(fallback_page_segmentation_mode=14)


def test_a_fallback_equal_to_the_primary_mode_is_not_a_retry():
    """Not an error, and not a second pass either.

    Tesseract is deterministic: re-running one mode over the same pixels
    returns the same nothing at twice the cost. Reporting "no retry" is the
    accurate description, and it keeps a caller who writes
    `TesseractOptions(page_segmentation_mode=6)` from having to know this
    option exists.
    """
    options = TesseractOptions(
        page_segmentation_mode=6, fallback_page_segmentation_mode=6
    )
    assert options.retries_segmentation is False


def test_no_fallback_is_configurable():
    assert (
        TesseractOptions(fallback_page_segmentation_mode=None).retries_segmentation
        is False
    )


# --- when the retry runs ----------------------------------------------------


def test_a_first_pass_that_reads_text_is_never_retried(image_ref, tesseract_data):
    """The retry must not touch an image the primary mode read.

    This is the whole safety argument for the feature. Mode 11 is a *worse*
    primary mode - measured over the same set it costs four true positives -
    so it may only ever run where the alternative is no reading at all.
    """
    runner = ScriptedRunner(
        {3: tesseract_data([("Net Qty 500 g", 92)]), 11: tesseract_data([("noise", 10)])}
    )
    result = TesseractOcrEngine(runner=runner).recognise(image_ref)

    assert runner.modes_run == [3]
    assert [block.text for block in result.blocks] == ["Net Qty 500 g"]
    assert result.raw["used_fallback_segmentation"] is False
    assert result.raw["page_segmentation_mode"] == 3


def test_an_empty_first_pass_is_retried_with_the_fallback_mode(
    image_ref, nothing, tesseract_data
):
    runner = ScriptedRunner({3: nothing, 11: tesseract_data([("MRP Rs. 250", 88)])})
    result = TesseractOcrEngine(runner=runner).recognise(image_ref)

    assert runner.modes_run == [3, 11]
    assert [block.text for block in result.blocks] == ["MRP Rs. 250"]


def test_the_retry_does_not_retry_itself(image_ref, nothing, tesseract_data):
    """One extra pass, not a chain.

    The second pass is constructed with its own fallback cleared, so a
    fallback that also reads nothing cannot start a third attempt.
    """
    runner = ScriptedRunner({3: nothing, 11: nothing})
    TesseractOcrEngine(runner=runner).recognise(image_ref)

    assert runner.modes_run == [3, 11]
    assert runner.calls[1][1].fallback_page_segmentation_mode is None


def test_a_disabled_fallback_leaves_an_empty_result_empty(image_ref, nothing):
    runner = ScriptedRunner({3: nothing})
    engine = TesseractOcrEngine(
        TesseractOptions(fallback_page_segmentation_mode=None), runner=runner
    )
    result = engine.recognise(image_ref)

    assert runner.modes_run == [3]
    assert result.blocks == ()
    assert result.raw["used_fallback_segmentation"] is False


def test_two_empty_passes_stay_empty_rather_than_inventing_text(
    image_ref, nothing
):
    """EMPTY is a correct answer for a blank or unreadable photograph."""
    runner = ScriptedRunner({3: nothing, 11: nothing})
    result = TesseractOcrEngine(runner=runner).recognise(image_ref)

    assert result.blocks == ()
    assert result.raw["used_fallback_segmentation"] is False
    assert result.raw["word_count"] == 0


# --- a retry that fails must not cost the primary pass's answer -------------


def test_a_failing_retry_keeps_the_empty_result_from_the_primary_pass(
    image_ref, nothing
):
    """The retry is a second chance, not part of the answer.

    The primary pass completed and produced a valid finding: this photograph
    was read and nothing usable was recognised. Letting an *optional* extra
    attempt turn that into `FAILED`/`ocr_failed` would replace an actionable
    result ("retake the panel") with a misleading one ("we could not process
    this image") - and would mean switching the fallback on could make a run
    fail that succeeded with it off.

    Same rule `ExtractionPipeline` applies to `release()` and to
    `unread_declarations()`: secondary work never overrules the outcome of the
    work it supplements.
    """
    runner = ScriptedRunner(
        {3: nothing, 11: OcrFailureError("Tesseract timed out or aborted")}
    )
    result = TesseractOcrEngine(runner=runner).recognise(image_ref)

    assert result.blocks == ()
    assert runner.modes_run == [3, 11]


def test_a_failing_retry_is_attempted_once_and_never_a_third_time(
    image_ref, nothing
):
    """The failure path must not reopen the retry it just swallowed."""
    runner = ScriptedRunner(
        {3: nothing, 11: OcrFailureError("Tesseract reported an error")}
    )
    TesseractOcrEngine(runner=runner).recognise(image_ref)

    assert len(runner.calls) == 2
    assert runner.modes_run == [3, 11]
    # The retry was still constructed with its own fallback cleared, so nothing
    # about the failure path could have started a chain.
    assert runner.calls[1][1].fallback_page_segmentation_mode is None


def test_a_failing_retry_leaves_the_recorded_metadata_describing_the_primary(
    image_ref, nothing
):
    """`raw` must describe the pass whose result is being returned.

    The blocks came from the primary pass, so every mode field has to say so.
    Recording `used_fallback_segmentation: True` for an attempt that produced
    nothing would misreport which segmentation read the pixels.
    """
    runner = ScriptedRunner({3: nothing, 11: OcrFailureError("boom")})
    raw = TesseractOcrEngine(runner=runner).recognise(image_ref).raw

    assert raw["used_fallback_segmentation"] is False
    assert raw["page_segmentation_mode"] == 3
    assert raw["requested_page_segmentation_mode"] == 3
    assert raw["word_count"] == 0
    assert raw["line_count"] == 0


@pytest.mark.parametrize(
    "failure",
    [
        OcrFailureError("Tesseract timed out or aborted"),
        InvalidImageError("Image could not be decoded: OSError"),
        EngineNotAvailableError("The tesseract binary was not found"),
    ],
)
def test_any_recorded_failure_from_the_retry_is_absorbed(
    image_ref, nothing, failure
):
    """Scoped to `LabelExtractError`, not to one subclass.

    Every operational failure this package raises descends from it, and which
    one a second pass happens to hit says nothing about the primary pass that
    already succeeded.
    """
    runner = ScriptedRunner({3: nothing, 11: failure})
    assert TesseractOcrEngine(runner=runner).recognise(image_ref).blocks == ()


def test_a_bug_in_the_retry_still_surfaces(image_ref, nothing):
    """Absorbing `LabelExtractError` is not absorbing everything.

    An exception outside the package's hierarchy is a defect in an engine, and
    recording it as "this photograph was blank" would hide it for ever.
    """
    runner = ScriptedRunner({3: nothing, 11: RuntimeError("a real bug")})
    with pytest.raises(RuntimeError):
        TesseractOcrEngine(runner=runner).recognise(image_ref)


def test_the_pipeline_reports_empty_not_failed_when_the_retry_fails(
    image_ref, nothing
):
    """The finding a caller actually sees.

    EMPTY carries no `error_code`; FAILED carries `ocr_failed` and is what the
    frontend branches on to say the image could not be processed.
    """
    from labelextract.pipeline import ExtractionPipeline

    runner = ScriptedRunner({3: nothing, 11: OcrFailureError("timed out")})
    pipeline = ExtractionPipeline(
        name="test", version="0", ocr_engine=TesseractOcrEngine(runner=runner)
    )
    result = pipeline.run(image_ref)

    assert result.status is ExtractionStatus.EMPTY
    assert result.error_code is None
    assert result.error_message is None


def test_a_failing_primary_pass_is_still_a_failure(image_ref, nothing):
    """The guard is on the retry alone.

    When the *first* pass fails there is no completed result to protect, and
    the run must be recorded as failed rather than as an empty photograph. A
    guard that swallowed this would turn every broken Tesseract install into
    "none of your labels have any text on them".
    """
    from labelextract.pipeline import ExtractionPipeline

    runner = ScriptedRunner({3: OcrFailureError("Tesseract reported an error")})
    with pytest.raises(OcrFailureError):
        TesseractOcrEngine(runner=runner).recognise(image_ref)

    # And only one pass was attempted - a failed primary is not retried.
    assert runner.modes_run == [3]

    pipeline = ExtractionPipeline(
        name="test",
        version="0",
        ocr_engine=TesseractOcrEngine(
            runner=ScriptedRunner({3: OcrFailureError("Tesseract reported an error")})
        ),
    )
    result = pipeline.run(image_ref)
    assert result.status is ExtractionStatus.FAILED
    assert result.error_code == "ocr_failed"


# --- what the run records ---------------------------------------------------


def test_the_recorded_mode_is_the_one_that_produced_the_result(
    image_ref, nothing, tesseract_data
):
    """A stored run must say what actually read the pixels.

    `raw` is persisted verbatim into `ExtractionRun.raw_output`. Recording the
    mode that was *asked for* first, when a different one produced the text,
    would make a disappointing run undiagnosable months later - which is the
    one job this mapping has.
    """
    runner = ScriptedRunner({3: nothing, 11: tesseract_data([("MRP Rs. 250", 88)])})
    result = TesseractOcrEngine(runner=runner).recognise(image_ref)

    assert result.raw["page_segmentation_mode"] == 11
    assert result.raw["requested_page_segmentation_mode"] == 3
    assert result.raw["used_fallback_segmentation"] is True


def test_the_word_geometry_recorded_is_the_retrys_own(
    image_ref, nothing, tesseract_data
):
    """`raw["words"]` must describe the pass whose blocks were kept.

    Two passes produce two different segmentations of the same photograph.
    Keeping the first pass's word list beside the second pass's lines would
    give a reviewer boxes that point at the wrong part of the package, and
    nothing would fail while it did.
    """
    runner = ScriptedRunner({3: nothing, 11: tesseract_data([("MRP Rs. 250", 88)])})
    result = TesseractOcrEngine(runner=runner).recognise(image_ref)

    words = [word["text"] for word in result.raw["words"]]
    assert words == ["MRP", "Rs.", "250"]
    assert result.raw["word_count"] == 3
    assert result.raw["line_count"] == 1


# --- through the pipeline ---------------------------------------------------


def test_the_pipeline_completes_where_it_used_to_report_empty(
    image_ref, nothing, tesseract_data
):
    """The user-visible point of the retry.

    EMPTY and COMPLETED-with-no-fields are different findings: the first says
    "we could not read this photograph", the second says "we read it and these
    declarations were not on it". Recovering text moves an image out of the
    first bucket, which is what a reviewer needs even when no declaration is
    extracted from it.
    """
    from labelextract.pipeline import ExtractionPipeline

    runner = ScriptedRunner({3: nothing, 11: tesseract_data([("Net Qty 500 g", 92)])})
    pipeline = ExtractionPipeline(
        name="test", version="0", ocr_engine=TesseractOcrEngine(runner=runner)
    )
    assert pipeline.run(image_ref).status is ExtractionStatus.COMPLETED

    single_pass = ExtractionPipeline(
        name="test",
        version="0",
        ocr_engine=TesseractOcrEngine(
            TesseractOptions(fallback_page_segmentation_mode=None),
            runner=ScriptedRunner({3: nothing}),
        ),
    )
    assert single_pass.run(image_ref).status is ExtractionStatus.EMPTY


def test_the_frozen_baseline_pipeline_does_not_retry():
    """0.1.0 ran one pass and must keep running one.

    A frozen reference that quietly acquired a retry would stop reproducing the
    runs recorded against it, which is the only reason it is still registered.
    """
    from labelextract.ocr import tesseract

    pipeline = tesseract.build_baseline_pipeline()
    assert pipeline.ocr_engine.options.retries_segmentation is False


def test_the_previous_pipeline_is_the_current_one_without_the_retry():
    """What makes 0.2.0 worth keeping registered: it isolates one change."""
    from labelextract.ocr import tesseract

    previous = tesseract.build_previous_pipeline().ocr_engine.options
    current = tesseract.build_pipeline().ocr_engine.options

    assert previous.page_segmentation_mode == current.page_segmentation_mode
    assert previous.engine_mode == current.engine_mode
    assert previous.retries_segmentation is False
    assert current.retries_segmentation is True
