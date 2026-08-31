"""Tesseract OCR, adapted to `interfaces.OcrEngine`.

Why Tesseract
-------------
Chosen against PaddleOCR, EasyOCR and docTR on the constraints this project
actually has:

- **Free, offline, and no account.** Apache-2.0, runs entirely on the machine.
  Nothing about an uploaded label photograph leaves the developer's laptop, and
  no API key exists to leak. That is a security property, not a convenience.
- **No model weights in the repository.** Language data is installed by the
  operating system's package manager into a system directory. Nothing to
  download at runtime, nothing to checksum, nothing that could end up in Git.
  The deep-learning alternatives all ship weights that would have to be fetched
  and cached.
- **It reports per-word confidence and per-word geometry.** The contracts here
  carry `TextBlock.confidence` and `BoundingBox` precisely so the UI can show
  *where on the package* a declaration was read. An engine that returned a
  bare string would leave both permanently None.
- **Devanagari is a package install, not a research project.**
  `tesseract-ocr-hin` exists; Indian labels are routinely bilingual. This is a
  requirement for this project specifically.
- **It installs in minutes on Windows, macOS and Linux.** Six people, mixed
  operating systems, a hackathon timeline. PaddleOCR's install is materially
  harder and pulls a deep-learning runtime.

The honest trade-off: Tesseract is weaker than the neural engines on curved
surfaces, reflective foil, low contrast and decorative type - which is a fair
description of most retail packaging photographed by hand. We expect to measure
that and, if the numbers justify it, to add a second engine *alongside* this
one rather than replacing it. `registry` is keyed by name and version so both
can be registered and compared on the same images.

**No accuracy figure for this engine appears anywhere in this repository**,
because none has been measured on our data. See `docs/evaluation-strategy.md`.

Blocks are lines, not words
---------------------------
`recognise()` groups Tesseract's word output into lines. Field extraction is
line-oriented - "MRP Rs. 250" is a fact about a line, not about the word "250"
- and a line-level block carries a union bounding box and a mean confidence
that are both meaningful. Word-level detail is not lost: it is kept verbatim in
`OcrResult.raw` so extraction can be re-run without re-running OCR.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from labelextract.contracts import BoundingBox, ImageRef, OcrResult, TextBlock
from labelextract.exceptions import (
    EngineNotAvailableError,
    InvalidImageError,
    LabelExtractError,
    OcrFailureError,
)
from labelextract.imageio import readable_path
from labelextract.interfaces import OcrEngine
from labelextract.pipeline import ExtractionPipeline

logger = logging.getLogger(__name__)

#: Pipeline name and version registered in `labelextract.registry`. This
#: versions *our pipeline* - engine + preprocessing + extraction rules - not
#: the Tesseract binary, whose version is recorded per run in `OcrResult.raw`.
#: Bump it whenever a change would make two runs incomparable.
NAME = "tesseract"
#: 0.3.0 adds the empty-result page-segmentation retry
#: (`TesseractOptions.fallback_page_segmentation_mode`). Nothing else about the
#: engine or the preprocessing moved; the primary mode is still 3 and the
#: preprocessing is still EXIF/grayscale/2x-upscale/autocontrast.
VERSION = "0.3.0"

#: The configuration 0.3.0 supersedes: identical, minus the retry. Registered
#: so the retry can be isolated and re-measured on any image rather than taken
#: on trust.
PREVIOUS_VERSION = "0.2.0"

#: The original configuration, kept registered rather than replaced.
#:
#: 0.2.0 changed the page-segmentation mode and turned on upscaling, which
#: makes its output incomparable with anything recorded under 0.1.0. All three
#: are registered so a stored `ExtractionRun` from before a change is still
#: reproducible, and so each change can be re-measured on any image rather than
#: taken on trust:
#:
#:     python -m labelextract.cli LABEL.jpg --pipeline-version 0.1.0
#:     python -m labelextract.cli LABEL.jpg --pipeline-version 0.2.0
#:     python -m labelextract.cli LABEL.jpg --pipeline-version 0.3.0
#:
#: It is frozen. Nothing about it should be tuned again - that is what makes it
#: a baseline.
#:
#: **What a pipeline version does and does not freeze.** It pins the engine and
#: preprocessing *configuration* written out in each factory below. It does
#: **not** pin `labelextract.fields.patterns`, which every registered pipeline
#: imports from one module: a pattern corrected today changes what 0.1.0 reads
#: as well. That has always been true here and is stated rather than implied,
#: because it is the difference between "re-runnable" and "byte-reproducible".
#: A run whose extraction rules must be reproduced exactly needs the commit,
#: not the version string.
BASELINE_VERSION = "0.1.0"

#: Tesseract language codes are passed to a subprocess argument. Only ISO 639-2
#: style codes are accepted, so nothing else can be smuggled into the command
#: line even if a language ever becomes user-configurable.
_LANGUAGE_CODE = re.compile(r"^[a-z]{3}(_[A-Za-z]{2,})?$")

#: Tesseract's sentinel for "this row is not a recognised word".
_NO_CONFIDENCE = -1


@dataclass(frozen=True)
class TesseractOptions:
    """Engine settings. Every value here changes what is recognised.

    Changing any of these changes results, so `VERSION` should be bumped when a
    default moves - otherwise two runs recorded under the same version are not
    comparable, which is the thing `engine_version` exists to prevent.
    """

    #: Languages to load, in Tesseract's priority order. "eng" alone by
    #: default: adding "hin" requires `tesseract-ocr-hin` to be installed, and
    #: an engine that fails on a machine without it would be worse than one
    #: that reads only the English on a bilingual panel. See ml/README.md.
    languages: tuple[str, ...] = ("eng",)
    #: Page segmentation mode. 3 = "fully automatic page segmentation, no
    #: orientation detection", i.e. let Tesseract find the text regions.
    #:
    #: This was 6 ("a single uniform block of text") until it was measured.
    #: 6 is right for an already-cropped panel and wrong for a photograph of a
    #: product on a desk, which is what people actually upload: it treats the
    #: whole frame - can, table, laptop, window - as one block and lets
    #: background clutter set the line structure. On Product 001's declaration
    #: close-up, 3 read the MRP, the street number and the ten-digit customer
    #: care number correctly where 6 misread all three.
    #:
    #: 3 is not universally better and the alternatives were not guessed at.
    #: Modes 4, 6, 11 and 12 were run over the same six photographs; 11 and 12
    #: ("sparse text") fragmented the declaration block into more than twice as
    #: many lines and cost extracted fields, and 4 sat between the two. What
    #: made 3 usable here is the upscaling that now precedes it - at the
    #: original size, 3 found no text at all on two of the six images. The two
    #: settings were chosen together and should be changed together.
    page_segmentation_mode: int = 3
    #: Page-segmentation mode retried when the primary mode recognised
    #: **nothing at all**. None disables the retry.
    #:
    #: Mode 3 does not degrade gracefully: on a photograph whose layout it
    #: cannot resolve it returns zero words rather than a poor reading, and the
    #: pipeline reports EMPTY. Measured over the 28 photographs of
    #: `our-eval-v0.3-usp-partial`, mode 3 returned nothing on 2 of them
    #: (`p002_01_back`, a cylindrical tube shot side-on; `p006_02_front`, a
    #: glare-lit printed film). Modes 6, 11 and 12 each read text on both.
    #:
    #: The trigger is **zero recognised blocks**, not "few" or "low
    #: confidence". A threshold would be a number nobody measured, and it would
    #: quietly re-segment images the primary mode read perfectly well; zero is
    #: the one case where there is nothing to lose, because the alternative
    #: outcome is already "we recognised no text on this label".
    #:
    #: **11, not 6**, and the difference was measured rather than reasoned
    #: about. Modes 4, 6, 11 and 12 were each tried as the fallback over the
    #: whole set:
    #:
    #: | Fallback | Chars recovered | Scored effect |
    #: |---|---|---|
    #: | 4 | 0 | mode 4 also reads nothing on those two images |
    #: | 6 | +1344 | **fabricated a retail sale price** on `p002_01_back` |
    #: | 11 | +876 | **no scored change at all** |
    #: | 12 | +843 | no scored change at all |
    #:
    #: Mode 6 recovers the most characters and is rejected for it. The extra
    #: text it finds on a badly lit curved surface includes the line
    #: `4 rs ne rm`, which the speculative no-keyword branch of the price
    #: detector reads as a retail sale price of 4 - a committed value for a
    #: declaration a human could not read, which is the single failure this
    #: architecture exists to prevent. Mode 11 recovers 65% as many characters
    #: and produced no such reading.
    #:
    #: Neither of these is a better *primary* mode. Over the whole set mode 6
    #: reads ~43% more characters and more of them are wrong (value accuracy
    #: 0.611 -> 0.429, silent error rate 0.417 -> 0.571), and mode 11 costs
    #: four true positives (recall 0.200 -> 0.156). That is precisely why this
    #: is a fallback: it only ever runs where the alternative is no reading at
    #: all.
    #:
    #: Cost: one extra Tesseract pass on the images that produced nothing, and
    #: none on the images that did - median latency over the set was unchanged.
    #: See ml/README.md.
    #:
    #: **It doubles the worst-case processing bound**, from `timeout_seconds` to
    #: twice it, because each pass carries its own cap. That is the correct
    #: reading of "one retry" and it stays bounded - the retry cannot chain, so
    #: two passes is the maximum however pathological the image. Set this to
    #: None where a single hard cap matters more than reading a difficult
    #: photograph.
    fallback_page_segmentation_mode: int | None = 11
    #: OCR engine mode. 3 = "whichever of legacy/LSTM is available"; modern
    #: builds resolve this to the LSTM recogniser.
    #:
    #: Measured on `our-eval-v0.3-usp-partial`: mode 1 (LSTM only) produced a
    #: byte-identical report to mode 3, confirming that this build resolves 3
    #: to the LSTM recogniser. Left at 3, which also works on a build that has
    #: only the legacy engine.
    engine_mode: int = 3
    #: Hard cap on a single recognition, in seconds. Unbounded processing on a
    #: hostile or pathological image is a denial-of-service vector.
    timeout_seconds: int = 30
    #: Drop words Tesseract scores below this (0-100). 0 keeps everything it
    #: reported. Not raised by default: discarding low-confidence words hides
    #: exactly the misreadings a reviewer needs to see, and the confidence
    #: travels with each block anyway.
    minimum_word_confidence: float = 0.0

    def __post_init__(self) -> None:
        if not self.languages:
            raise ValueError("At least one language must be configured")
        for code in self.languages:
            if not _LANGUAGE_CODE.match(code):
                raise ValueError(f"Not a valid Tesseract language code: {code!r}")
        if not 0 <= self.page_segmentation_mode <= 13:
            raise ValueError("page_segmentation_mode must be within 0-13")
        if self.fallback_page_segmentation_mode is not None and not (
            0 <= self.fallback_page_segmentation_mode <= 13
        ):
            raise ValueError(
                "fallback_page_segmentation_mode must be within 0-13 or None"
            )
        if not 0 <= self.engine_mode <= 3:
            raise ValueError("engine_mode must be within 0-3")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 0 <= self.minimum_word_confidence <= 100:
            raise ValueError("minimum_word_confidence must be within 0-100")

    @property
    def retries_segmentation(self) -> bool:
        """Whether an empty first pass is worth a second one.

        A fallback equal to the primary mode is not an error and not a retry:
        Tesseract is deterministic, so re-running the same mode over the same
        pixels returns the same nothing at twice the cost. Reporting it as
        "no retry configured" is the accurate description of what will happen,
        and it keeps `TesseractOptions(page_segmentation_mode=6)` - a perfectly
        reasonable thing for a caller to write - from raising.
        """
        return (
            self.fallback_page_segmentation_mode is not None
            and self.fallback_page_segmentation_mode != self.page_segmentation_mode
        )

    @property
    def language_argument(self) -> str:
        return "+".join(self.languages)

    @property
    def config_argument(self) -> str:
        """The `--psm`/`--oem` flags, built only from validated integers."""
        return f"--psm {self.page_segmentation_mode} --oem {self.engine_mode}"


class TesseractRunner:
    """The only part of this module that touches Tesseract itself.

    Split out so `TesseractOcrEngine` - which holds all of the parsing,
    grouping and error-mapping logic worth testing - can be tested exhaustively
    with a deterministic fake and no binary installed. That is what keeps the
    test suite runnable on a fresh clone, in CI, and offline.
    """

    def version(self) -> str | None:
        """Tesseract's version string, or None if it cannot be determined."""
        raise NotImplementedError

    def word_data(self, path: Path, options: TesseractOptions) -> Mapping[str, Sequence]:
        """Return Tesseract's word-level TSV output as columns.

        The shape is pytesseract's `image_to_data(output_type=DICT)`: parallel
        lists keyed by `level`, `block_num`, `par_num`, `line_num`, `word_num`,
        `left`, `top`, `width`, `height`, `conf`, `text`.
        """
        raise NotImplementedError


class PytesseractRunner(TesseractRunner):
    """Real Tesseract, via the `pytesseract` wrapper.

    `pytesseract` builds its own argument list and never uses a shell, so no
    string from an image or a filename is interpreted as a command. The values
    this class supplies are validated by `TesseractOptions` before they get
    here.
    """

    def __init__(self, tesseract_cmd: str | None = None) -> None:
        """
        Args:
            tesseract_cmd: Absolute path to the binary. Needed on Windows,
                where the installer does not add it to PATH. Leave as None to
                let pytesseract find `tesseract` on PATH.
        """
        self._tesseract_cmd = tesseract_cmd

    def _pytesseract(self):
        try:
            import pytesseract
        except ImportError as exc:
            raise EngineNotAvailableError(
                "pytesseract is not installed. Install the OCR extra: "
                "pip install -e ./ml[ocr]"
            ) from exc
        if self._tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd
        return pytesseract

    def version(self) -> str | None:
        pytesseract = self._pytesseract()
        try:
            return str(pytesseract.get_tesseract_version())
        except pytesseract.TesseractNotFoundError as exc:
            # "The binary is missing" and "I could not parse its version
            # banner" are different facts and must not collapse into one
            # return value. `warmup()` exists to surface the first at startup
            # rather than on a user's first upload, and swallowing it here
            # would make that call do nothing at all.
            raise EngineNotAvailableError(
                "The tesseract binary was not found. Install Tesseract OCR and "
                "make sure it is on PATH; see ml/README.md."
            ) from exc
        except Exception:
            # Anything else: recorded as unknown rather than raising. Not
            # knowing the version is a gap in the audit trail, not a reason to
            # refuse a run the engine can otherwise complete.
            logger.warning("Could not determine the Tesseract version", exc_info=True)
            return None

    def word_data(self, path: Path, options: TesseractOptions) -> Mapping[str, Sequence]:
        pytesseract = self._pytesseract()
        try:
            from PIL import Image
        except ImportError as exc:
            raise EngineNotAvailableError(
                "Pillow is not installed. Install the OCR extra: "
                "pip install -e ./ml[ocr]"
            ) from exc

        try:
            with Image.open(path) as image:
                image.load()
                return pytesseract.image_to_data(
                    image,
                    lang=options.language_argument,
                    config=options.config_argument,
                    timeout=options.timeout_seconds,
                    output_type=pytesseract.Output.DICT,
                )
        # Order matters, and not only for tidiness: pytesseract's exceptions
        # subclass builtins, so a broader clause placed first silently swallows
        # a narrower one.
        #
        #     TesseractNotFoundError -> OSError        (the binary is missing)
        #     TesseractError         -> RuntimeError   (the binary reported an error)
        #
        # With `except RuntimeError` first, every genuine Tesseract error was
        # recorded as "timed out or aborted" and the TesseractError clause was
        # unreachable. Both still map to the same `ocr_failed` code, but the
        # message is what an operator reads in `ExtractionRun.error_message`,
        # and "timed out" sends them to look at the wrong thing.
        except pytesseract.TesseractNotFoundError as exc:
            raise EngineNotAvailableError(
                "The tesseract binary was not found. Install Tesseract OCR and "
                "make sure it is on PATH; see ml/README.md."
            ) from exc
        except pytesseract.TesseractError as exc:
            raise OcrFailureError(f"Tesseract reported an error: {exc}") from exc
        except FileNotFoundError as exc:
            raise InvalidImageError(f"Image file does not exist: {path}") from exc
        except OSError as exc:
            raise InvalidImageError(
                f"Image could not be decoded: {exc.__class__.__name__}"
            ) from exc
        except RuntimeError as exc:
            # What is left of RuntimeError once TesseractError is taken out:
            # pytesseract raises a plain one when `timeout` expires.
            raise OcrFailureError(f"Tesseract timed out or aborted: {exc}") from exc


class TesseractOcrEngine(OcrEngine):
    """Recognises text and its position, and nothing else.

    It reports characters and geometry. It never decides what a string *means*
    - that is `FieldExtractor`'s job, and keeping the two apart is what lets a
    misreading be corrected independently of a misinterpretation.
    """

    name = NAME
    version = VERSION

    def __init__(
        self,
        options: TesseractOptions | None = None,
        *,
        runner: TesseractRunner | None = None,
    ) -> None:
        """
        Args:
            options: Engine settings.
            runner: Injected for tests. Defaults to real Tesseract.
        """
        self.options = options or TesseractOptions()
        self._runner = runner or PytesseractRunner()

    def warmup(self) -> None:
        """Resolve the binary at startup rather than on a user's first upload.

        Raises:
            EngineNotAvailableError: pytesseract or the binary is missing.
        """
        self._runner.version()

    def recognise(self, image: ImageRef) -> OcrResult:
        path = readable_path(image)
        options = self.options

        words = self._recognise_with(path, options)
        blocks = _lines_from(words)

        fallback_mode: int | None = None
        if not blocks and options.retries_segmentation:
            # Nothing at all was recognised. There is no reading to protect, so
            # a second segmentation strategy costs only time. See
            # `TesseractOptions.fallback_page_segmentation_mode` for why the
            # trigger is zero rather than a threshold.
            retry = replace(
                options,
                page_segmentation_mode=options.fallback_page_segmentation_mode,
                fallback_page_segmentation_mode=None,
            )
            try:
                retry_words = self._recognise_with(path, retry)
            except LabelExtractError as exc:
                # The retry is a *second chance*, not part of the answer. The
                # primary pass already completed and produced a valid finding -
                # "this photograph was read and nothing usable was recognised" -
                # and letting an optional extra attempt turn that into
                # `FAILED`/`ocr_failed` would replace an actionable result
                # ("retake the panel") with a misleading one ("we could not
                # process this image"). It would also mean turning the fallback
                # *on* could make a run fail that succeeded with it off.
                #
                # The same rule `ExtractionPipeline` applies to `release()` and
                # to `unread_declarations()`: secondary work cannot be allowed
                # to overrule the outcome of the work it is supplementing.
                #
                # Scoped to `LabelExtractError` deliberately - every operational
                # failure this package raises descends from it, and anything
                # that does not is a bug in an engine and must still surface
                # loudly rather than be recorded as an empty photograph.
                #
                # Only the exception's class is logged. The message can carry
                # Tesseract's own stderr, and nothing about a user's label
                # belongs in our logs.
                logger.warning(
                    "Fallback page-segmentation pass (--psm %s) failed with %s "
                    "after --psm %s recognised nothing; keeping the empty "
                    "result from the primary pass",
                    retry.page_segmentation_mode,
                    exc.__class__.__name__,
                    options.page_segmentation_mode,
                )
            else:
                retry_blocks = _lines_from(retry_words)
                if retry_blocks:
                    words, blocks = retry_words, retry_blocks
                    fallback_mode = retry.page_segmentation_mode

        return OcrResult(
            blocks=blocks,
            raw={
                "engine": NAME,
                "pipeline_version": VERSION,
                "tesseract_version": self._runner.version(),
                "languages": list(options.languages),
                # The mode whose output this result carries, which is the
                # fallback's when the fallback produced it. A stored run must
                # say what actually read the pixels, not what was asked for
                # first.
                "page_segmentation_mode": (
                    fallback_mode
                    if fallback_mode is not None
                    else options.page_segmentation_mode
                ),
                "requested_page_segmentation_mode": options.page_segmentation_mode,
                #: True when the primary mode recognised nothing and the retry
                #: did. Recorded so a disappointing run is diagnosable later,
                #: and so the frequency of the retry is measurable rather than
                #: assumed.
                "used_fallback_segmentation": fallback_mode is not None,
                "engine_mode": options.engine_mode,
                "word_count": len(words),
                "line_count": len(blocks),
                # Word-level detail, kept so field extraction can be improved
                # and re-run over a stored result without paying for OCR again.
                "words": [word.as_dict() for word in words],
            },
        )

    def _recognise_with(
        self, path: Path, options: TesseractOptions
    ) -> tuple[_Word, ...]:
        """One Tesseract pass, parsed into words."""
        data = self._runner.word_data(path, options)
        try:
            return _words_from(data, options.minimum_word_confidence)
        except (KeyError, TypeError, ValueError) as exc:
            # The engine ran but produced something we cannot read. An
            # operational failure, recorded as such - not a bug in our code and
            # not a claim that the package had no text on it.
            raise OcrFailureError(
                f"Tesseract output could not be parsed: {exc.__class__.__name__}"
            ) from exc


# --- parsing ----------------------------------------------------------------


@dataclass(frozen=True)
class _Word:
    """One recognised word, before it is grouped into a line."""

    text: str
    line_key: tuple[int, int, int, int]
    left: int
    top: int
    width: int
    height: int
    #: 0.0-1.0, or None when Tesseract reported no usable score.
    confidence: float | None
    order: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "confidence": self.confidence,
            "line": list(self.line_key),
        }


def _words_from(
    data: Mapping[str, Sequence], minimum_confidence: float
) -> tuple[_Word, ...]:
    """Turn Tesseract's parallel columns into words, dropping the non-words.

    Tesseract emits a row per layout element - page, block, paragraph, line,
    word - and only the word rows carry text. Empty and whitespace-only rows
    are discarded here because they would otherwise become blank lines that
    field extraction has to keep re-checking.
    """
    texts = data["text"]
    count = len(texts)
    words: list[_Word] = []

    for index in range(count):
        text = str(texts[index]).strip()
        if not text:
            continue

        confidence = _confidence_at(data, index)
        if (
            confidence is not None
            and minimum_confidence > 0
            and confidence * 100 < minimum_confidence
        ):
            continue

        words.append(
            _Word(
                text=text,
                line_key=(
                    _int_at(data, "page_num", index),
                    _int_at(data, "block_num", index),
                    _int_at(data, "par_num", index),
                    _int_at(data, "line_num", index),
                ),
                left=_int_at(data, "left", index),
                top=_int_at(data, "top", index),
                width=_int_at(data, "width", index),
                height=_int_at(data, "height", index),
                confidence=confidence,
                order=index,
            )
        )
    return tuple(words)


def _lines_from(words: Sequence[_Word]) -> tuple[TextBlock, ...]:
    """Group words into lines, preserving Tesseract's reading order.

    A line's confidence is the mean of its words'. That is a summary, not a
    measurement of the line, so it is only reported when at least one word
    carried a score - a line of unscored words stays None rather than being
    given a number nobody measured.
    """
    grouped: dict[tuple[int, int, int, int], list[_Word]] = {}
    for word in words:
        grouped.setdefault(word.line_key, []).append(word)

    blocks: list[TextBlock] = []
    for line_key in sorted(grouped):
        line_words = sorted(grouped[line_key], key=lambda w: w.order)
        text = " ".join(word.text for word in line_words)
        if not text.strip():
            continue
        blocks.append(
            TextBlock(
                text=text,
                box=_union_box(line_words),
                confidence=_mean_confidence(line_words),
            )
        )
    return tuple(blocks)


def _union_box(words: Sequence[_Word]) -> BoundingBox | None:
    """Smallest box containing every word on the line, or None if degenerate."""
    usable = [w for w in words if w.width > 0 and w.height > 0]
    if not usable:
        return None
    left = min(w.left for w in usable)
    top = min(w.top for w in usable)
    right = max(w.left + w.width for w in usable)
    bottom = max(w.top + w.height for w in usable)
    # Tesseract can report a small negative origin for a glyph clipped at the
    # edge; BoundingBox rejects those, and clamping is the correct reading of
    # "the box starts at the edge of the image".
    left = max(0, left)
    top = max(0, top)
    if right <= left or bottom <= top:
        return None
    return BoundingBox(x=left, y=top, width=right - left, height=bottom - top)


def _mean_confidence(words: Sequence[_Word]) -> float | None:
    scored = [w.confidence for w in words if w.confidence is not None]
    if not scored:
        return None
    return sum(scored) / len(scored)


def _confidence_at(data: Mapping[str, Sequence], index: int) -> float | None:
    """Read Tesseract's 0-100 score and rescale it to the contract's 0-1.

    Returns None for the -1 sentinel and for anything unparseable. None means
    "not reported" and must never be read as zero - `contracts` and the
    database column are both nullable for exactly this reason.
    """
    raw = data.get("conf")
    if raw is None or index >= len(raw):
        return None
    try:
        value = float(raw[index])
    except (TypeError, ValueError):
        return None
    if value <= _NO_CONFIDENCE:
        return None
    return max(0.0, min(1.0, value / 100.0))


def _int_at(data: Mapping[str, Sequence], key: str, index: int) -> int:
    column = data.get(key)
    if column is None or index >= len(column):
        return 0
    try:
        return int(column[index])
    except (TypeError, ValueError):
        return 0


# --- pipeline factory -------------------------------------------------------


def build_pipeline() -> ExtractionPipeline:
    """Factory registered in `labelextract.registry` under NAME/VERSION.

    Wires the three stages that make up the first real extraction path:
    Pillow preparation, Tesseract recognition, rule-based interpretation.

    Imported lazily inside the function so that registering this pipeline at
    import time costs nothing and needs neither Pillow nor pytesseract present.
    A machine with no OCR stack installed can still import `labelextract`, list
    the registry, and run the whole test suite.
    """
    from labelextract.fields import RuleBasedFieldExtractor
    from labelextract.preprocessing import (
        UPSCALE_TO_DIMENSION,
        PillowPreprocessor,
        PreprocessingConfig,
    )

    return ExtractionPipeline(
        name=NAME,
        version=VERSION,
        ocr_engine=TesseractOcrEngine(),
        # Upscaling is asked for here rather than defaulted inside
        # `PreprocessingConfig`, because it is *this pipeline* - this
        # preprocessing plus this page-segmentation mode - that was measured.
        # A bare `PillowPreprocessor()` stays conservative for anyone building
        # something else out of these parts.
        preprocessor=PillowPreprocessor(
            PreprocessingConfig(min_dimension=UPSCALE_TO_DIMENSION)
        ),
        field_extractor=RuleBasedFieldExtractor(),
    )


def build_previous_pipeline() -> ExtractionPipeline:
    """The 0.2.0 configuration: 0.3.0 without the empty-result retry.

    Registered so the retry can be isolated on any image. Everything else is
    written out explicitly, for the same reason `build_baseline_pipeline` does
    it: a factory that inherits a default stops reproducing the version it
    names as soon as the default moves.

        python -m labelextract.cli LABEL.jpg --pipeline-version 0.2.0
        python -m labelextract.cli LABEL.jpg --pipeline-version 0.3.0

    The two differ on exactly one photograph in ten or so - the retry only
    fires where the primary mode recognised nothing at all.
    """
    from labelextract.fields import RuleBasedFieldExtractor
    from labelextract.preprocessing import (
        UPSCALE_TO_DIMENSION,
        PillowPreprocessor,
        PreprocessingConfig,
    )

    return ExtractionPipeline(
        name=NAME,
        version=PREVIOUS_VERSION,
        ocr_engine=TesseractOcrEngine(
            TesseractOptions(
                page_segmentation_mode=3,
                fallback_page_segmentation_mode=None,
                engine_mode=3,
            )
        ),
        preprocessor=PillowPreprocessor(
            PreprocessingConfig(min_dimension=UPSCALE_TO_DIMENSION)
        ),
        field_extractor=RuleBasedFieldExtractor(),
    )


def build_baseline_pipeline() -> ExtractionPipeline:
    """The 0.1.0 configuration, registered alongside `build_pipeline`.

    Every setting is written out here rather than inherited from a default, so
    this pipeline keeps behaving as 0.1.0 did no matter what the defaults
    become later. That is the whole point of it: a frozen reference to measure
    a change against, and a way to reproduce a run recorded before the change.

    Kept deliberately free of tuning. If it needs adjusting, the thing that
    needs adjusting is 0.2.0.
    """
    from labelextract.fields import RuleBasedFieldExtractor
    from labelextract.preprocessing import PillowPreprocessor, PreprocessingConfig

    return ExtractionPipeline(
        name=NAME,
        version=BASELINE_VERSION,
        ocr_engine=TesseractOcrEngine(
            # `fallback_page_segmentation_mode=None` is not an omission. 0.1.0
            # ran one Tesseract pass and reported EMPTY when it found nothing,
            # and a frozen reference that quietly acquired a retry would stop
            # reproducing the runs recorded against it.
            TesseractOptions(
                page_segmentation_mode=6,
                fallback_page_segmentation_mode=None,
                engine_mode=3,
            )
        ),
        preprocessor=PillowPreprocessor(
            PreprocessingConfig(min_dimension=None, max_dimension=None)
        ),
        field_extractor=RuleBasedFieldExtractor(),
    )
