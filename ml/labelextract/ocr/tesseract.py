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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from labelextract.contracts import BoundingBox, ImageRef, OcrResult, TextBlock
from labelextract.exceptions import (
    EngineNotAvailableError,
    InvalidImageError,
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
#: 0.2.1 changed the *extraction* rules, not the engine settings: a
#: keyword-shaped batch value is now refused, an ambiguous net quantity is
#: withheld, and a number is no longer truncated to three digits. Two runs
#: recorded either side of it are not comparable, so the version moves.
#:
#: 0.2.0 is **not** registered alongside it, which departs from the rule the
#: rest of this file follows. Keeping a version resolvable exists so a stored
#: run stays reproducible; 0.2.0's extraction layer fabricated batch numbers
#: for packages that declared none, and reproducing that would mean shipping a
#: switch whose only effect is to turn a violation into a pass. The changes
#: also live inside `RuleBasedFieldExtractor` itself, which every registered
#: version shares, so preserving them would mean forking a known-unsafe
#: extractor. A run recorded under 0.2.0 stays interpretable - its name and
#: version are stored as plain text - it just cannot be re-executed.
VERSION = "0.2.1"

#: The original configuration, kept registered rather than replaced.
#:
#: The 0.2.x line changed the page-segmentation mode and turned on upscaling,
#: which makes its output incomparable with anything recorded under 0.1.0. This
#: one stays registered so a stored `ExtractionRun` from before that change is
#: still reproducible, and so the improvement can be re-measured on any image
#: rather than taken on trust.
#:
#: **`registry` holds exactly two tesseract versions: this one and `VERSION`.**
#: 0.2.0 is the gap, for the reason given above it, so the pair that resolve
#: today are:
#:
#:     python -m labelextract.cli LABEL.jpg --pipeline-version 0.1.0
#:     python -m labelextract.cli LABEL.jpg --pipeline-version 0.2.1
#:
#: `--pipeline-version 0.2.0` raises `PipelineNotFoundError`. That is a real
#: departure from the register-alongside convention the rest of this file
#: describes, and it is recorded here as the current state rather than tidied
#: away: every version this file names is either registered or explicitly said
#: not to be.
#:
#: It is frozen. Nothing about it should be tuned again - that is what makes it
#: a baseline.
BASELINE_VERSION = "0.1.0"

#: Tesseract language codes are passed to a subprocess argument. Only ISO 639-2
#: style codes are accepted, so nothing else can be smuggled into the command
#: line even if a language ever becomes user-configurable.
_LANGUAGE_CODE = re.compile(r"^[a-z]{3}(_[A-Za-z]{2,})?$")

#: Tesseract's sentinel for "this row is not a recognised word".
_NO_CONFIDENCE = -1

#: The only rotations whose bounding-box mapping is exact. See
#: `_unrotated_word_data`.
_RIGHT_ANGLES = frozenset({0, 90, 180, 270})


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
    #: OCR engine mode. 3 = "whichever of legacy/LSTM is available"; modern
    #: builds resolve this to the LSTM recogniser.
    engine_mode: int = 3
    #: Hard cap on a single recognition, in seconds. Unbounded processing on a
    #: hostile or pathological image is a denial-of-service vector.
    timeout_seconds: int = 30
    #: Drop words Tesseract scores below this (0-100). 0 keeps everything it
    #: reported. Not raised by default: discarding low-confidence words hides
    #: exactly the misreadings a reviewer needs to see, and the confidence
    #: travels with each block anyway.
    minimum_word_confidence: float = 0.0
    #: Ask Tesseract's OSD which way up the page is, and rotate before
    #: recognising when it is confident.
    #:
    #: **Off by default, and that is a measured decision rather than caution.**
    #:
    #: A photograph of a label rotated 90 degrees is unreadable to this
    #: pipeline - `--psm 3` is explicitly "no orientation detection" - so OSD
    #: looks like the obvious fix. It was measured on the ten-product set
    #: before being wired in, and the numbers did not support turning it on:
    #:
    #: - **OSD was wrong on the image that needed it.** On a rotated masala
    #:   pack it reported `rotate=180` at confidence 1.32. The rotation that
    #:   actually recovers the declaration panel is 270, which lifts the
    #:   recognised legal-metrology keywords from 0/7 to 5/7. Following OSD
    #:   would have reached 1/7.
    #: - **OSD was confidently wrong on a good image.** On the best-recognised
    #:   carton in the set it reported `rotate=180` - at confidence 0.12. Acting
    #:   on that would have cut the recognised text from 1223 characters to 956
    #:   and destroyed the one image the pipeline reads well.
    #: - **It is not cheap.** An OSD pass measured 578-589 ms against a full
    #:   recognition pass of 378-702 ms on the same images: an 82-156% increase
    #:   in per-image processing time.
    #:
    #: So it is available, correct, and off. `minimum_orientation_confidence`
    #: is what makes enabling it safe: on the images above, a threshold of 2.0
    #: refuses both wrong answers. Anyone turning this on should re-measure on
    #: their own images first - and note that a threshold high enough to be
    #: safe made it a no-op on every image in our set.
    #:
    #: Rotating never costs a second recognition pass: the image is rotated
    #: before the single `image_to_data` call, and boxes are mapped back to
    #: source coordinates exactly.
    orientation_detection: bool = False
    #: OSD confidence below which its answer is ignored. Tesseract's own scale,
    #: which is unbounded and typically 0-5; see `orientation_detection`.
    minimum_orientation_confidence: float = 2.0

    def __post_init__(self) -> None:
        if not self.languages:
            raise ValueError("At least one language must be configured")
        for code in self.languages:
            if not _LANGUAGE_CODE.match(code):
                raise ValueError(f"Not a valid Tesseract language code: {code!r}")
        if not 0 <= self.page_segmentation_mode <= 13:
            raise ValueError("page_segmentation_mode must be within 0-13")
        if not 0 <= self.engine_mode <= 3:
            raise ValueError("engine_mode must be within 0-3")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 0 <= self.minimum_word_confidence <= 100:
            raise ValueError("minimum_word_confidence must be within 0-100")
        if self.minimum_orientation_confidence < 0:
            raise ValueError("minimum_orientation_confidence must not be negative")

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

        When `options.orientation_detection` is on and OSD is confident, the
        image is rotated before recognition and the returned geometry is
        already mapped back to the *source* image's coordinate system, so a
        caller never sees rotated-space boxes.
        """
        raise NotImplementedError

    def orientation(
        self, path: Path, options: TesseractOptions
    ) -> tuple[int, float] | None:
        """Tesseract's view of which way up the page is.

        Returns `(degrees_to_rotate, confidence)`, or None when OSD could not
        answer. `degrees_to_rotate` is **counter-clockwise** and one of
        0/90/180/270, ready to hand to Pillow.

        The conversion happens here, once, and it matters: Tesseract's OSD
        reports the rotation to apply *clockwise*, while `Image.rotate()` turns
        counter-clockwise. Passing OSD's number straight to Pillow turns a
        90-degree error into a 180-degree one - the image comes out upside
        down, recognition still returns text, and nothing fails. Measured on a
        deliberately rotated pack: OSD said `rotate=90`, applying 90 CCW left
        the net quantity unreadable, and applying it clockwise recovered it.

        None rather than `(0, 0.0)` when OSD fails: "the page is upright" and
        "nobody could tell" are different facts, and only the first is a
        reading. OSD legitimately fails on images with too little text to
        analyse, which is common on a front panel.
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
                rotation = 0
                if options.orientation_detection:
                    rotation = self._rotation_for(path, options)
                source_size = image.size
                if rotation:
                    # Rotated before the single recognition pass, never after
                    # a first one: enabling orientation detection costs an OSD
                    # pass, not a second full OCR.
                    image = image.rotate(rotation, expand=True)
                data = pytesseract.image_to_data(
                    image,
                    lang=options.language_argument,
                    config=options.config_argument,
                    timeout=options.timeout_seconds,
                    output_type=pytesseract.Output.DICT,
                )
                if rotation:
                    data = _unrotated_word_data(data, rotation, source_size)
                return data
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

    def _rotation_for(self, path: Path, options: TesseractOptions) -> int:
        """The rotation to apply, or 0 to leave the image alone.

        Every failure here returns 0. Orientation detection is an *optimisation*
        on top of a pipeline that already works on upright images; a page whose
        orientation cannot be determined must be recognised as it arrived, not
        refused. Rotating on a guess is the one outcome worse than not
        rotating, because it destroys images that were fine.
        """
        try:
            answer = self.orientation(path, options)
        except EngineNotAvailableError:
            raise
        except Exception:
            logger.debug("Orientation detection failed; recognising as-is",
                         exc_info=True)
            return 0
        if answer is None:
            return 0
        degrees, confidence = answer
        if confidence < options.minimum_orientation_confidence:
            logger.debug(
                "Ignoring OSD rotation %s: confidence %.2f is below the %.2f "
                "threshold", degrees, confidence,
                options.minimum_orientation_confidence,
            )
            return 0
        return degrees % 360

    def orientation(
        self, path: Path, options: TesseractOptions
    ) -> tuple[int, float] | None:
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
                osd = pytesseract.image_to_osd(
                    image,
                    timeout=options.timeout_seconds,
                    output_type=pytesseract.Output.DICT,
                )
        except pytesseract.TesseractNotFoundError as exc:
            raise EngineNotAvailableError(
                "The tesseract binary was not found. Install Tesseract OCR and "
                "make sure it is on PATH; see ml/README.md."
            ) from exc
        except Exception:
            # OSD refuses on images with too little text to analyse, which is
            # normal for a front panel. Not a reading, so not a result.
            logger.debug("OSD produced no orientation", exc_info=True)
            return None

        try:
            clockwise = int(osd["rotate"]) % 360
            confidence = float(osd["orientation_conf"])
        except (KeyError, TypeError, ValueError):
            return None
        # OSD's clockwise convention -> Pillow's counter-clockwise one.
        degrees = (360 - clockwise) % 360
        if degrees not in _RIGHT_ANGLES:
            # Only right angles are exactly invertible for bounding boxes, and
            # an inexact box is a claim about where on the package a
            # declaration was read.
            return None
        return degrees, confidence


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
        data = self._runner.word_data(path, self.options)

        try:
            words = _words_from(data, self.options.minimum_word_confidence)
        except (KeyError, TypeError, ValueError) as exc:
            # The engine ran but produced something we cannot read. An
            # operational failure, recorded as such - not a bug in our code and
            # not a claim that the package had no text on it.
            raise OcrFailureError(
                f"Tesseract output could not be parsed: {exc.__class__.__name__}"
            ) from exc

        blocks = _lines_from(words)
        return OcrResult(
            blocks=blocks,
            raw={
                "engine": NAME,
                "pipeline_version": VERSION,
                "tesseract_version": self._runner.version(),
                "languages": list(self.options.languages),
                "page_segmentation_mode": self.options.page_segmentation_mode,
                "engine_mode": self.options.engine_mode,
                "word_count": len(words),
                "line_count": len(blocks),
                # Word-level detail, kept so field extraction can be improved
                # and re-run over a stored result without paying for OCR again.
                "words": [word.as_dict() for word in words],
            },
        )


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


def _unrotated_word_data(
    data: Mapping[str, Sequence], rotation: int, source_size: tuple[int, int]
) -> dict[str, Sequence]:
    """Map word geometry from a rotated image back to source coordinates.

    Rotation is why bounding boxes and orientation correction cannot be done
    independently. Recognising a rotated copy puts every box in the rotated
    image's coordinate system, so an evidence overlay drawn on the photograph
    the reviewer is looking at would point at the wrong part of the package -
    and nothing would fail while it did. That is the same defect resizing had
    before `ExtractionPipeline` learned to map boxes back, and it is worse
    here, because a 90-degree error moves a box to a completely different
    region rather than merely scaling it.

    This mapping is **exact**, not approximate, which is why `orientation()`
    refuses any angle that is not a right angle.

    The arithmetic is in **edge coordinates, not pixel centres**, and the
    difference is not cosmetic. Tesseract reports a box as `left, top, width,
    height`, so `left + width` is the exclusive right edge - one past the last
    pixel. Treating coordinates as the continuous grid lines between pixels,
    Pillow's counter-clockwise `rotate(angle, expand=True)` maps a source of
    `W x H` as:

        90   source (x, y) -> rotated (y, W-x),  rotated size H x W
        180  source (x, y) -> rotated (W-x, H-y), size W x H
        270  source (x, y) -> rotated (H-y, x),  rotated size H x W

    and `_unrotate_point` inverts exactly those. Written in pixel-centre form
    the constants would each gain a `-1` (`W-1-x`), which is the natural way to
    write it and is **wrong here**: applied to an exclusive corner it shrinks
    every box by a pixel on the rotated axis and shifts it by one. Mapping both
    corners in edge coordinates and taking min/max returns the source rectangle
    with no error at all, which
    `tests/test_ocr_tesseract.py::test_a_rotated_box_maps_back_to_its_source_box`
    pins against a real Pillow rotation rather than against this comment.

    Corners are re-normalised afterwards because the inverse of a rotation
    swaps which corner is top-left.

    The `raw` word list downstream is documented as verbatim engine output, and
    it stays that way: this rewrites geometry only, before anything reads it,
    so no consumer ever sees a coordinate system it was not told about.
    """
    if rotation % 360 == 0:
        return dict(data)

    width, height = source_size
    mapped = {key: list(values) for key, values in data.items()}
    count = len(mapped.get("text", []))

    for index in range(count):
        left = _int_at(data, "left", index)
        top = _int_at(data, "top", index)
        box_width = _int_at(data, "width", index)
        box_height = _int_at(data, "height", index)

        corners = [
            _unrotate_point(left, top, rotation, width, height),
            _unrotate_point(
                left + box_width, top + box_height, rotation, width, height
            ),
        ]
        xs = [point[0] for point in corners]
        ys = [point[1] for point in corners]
        mapped["left"][index] = min(xs)
        mapped["top"][index] = min(ys)
        mapped["width"][index] = max(xs) - min(xs)
        mapped["height"][index] = max(ys) - min(ys)

    return mapped


def _unrotate_point(
    x: int, y: int, rotation: int, width: int, height: int
) -> tuple[int, int]:
    """One rotated-space point, expressed in source-image space.

    Edge coordinates, not pixel centres - see `_unrotated_word_data`. A single
    point round-trips one pixel off along each rotated axis by design; a *box*
    round-trips exactly, because its second corner is exclusive and the offset
    cancels. Boxes are the only thing this is used for.
    """
    if rotation == 90:
        # forward: (x, y) -> (y, W-x); inverse of the rotated point (x, y):
        return (width - y, x)
    if rotation == 180:
        return (width - x, height - y)
    if rotation == 270:
        # forward: (x, y) -> (H-y, x); inverse of the rotated point (x, y):
        return (y, height - x)
    return (x, y)


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


def build_baseline_pipeline() -> ExtractionPipeline:
    """The 0.1.0 configuration, registered alongside `build_pipeline`.

    Every setting is written out here rather than inherited from a default, so
    this pipeline keeps behaving as 0.1.0 did no matter what the defaults
    become later. That is the whole point of it: a frozen reference to measure
    a change against, and a way to reproduce a run recorded before the change.

    Kept deliberately free of tuning. If it needs adjusting, the thing that
    needs adjusting is the current `VERSION`.
    """
    from labelextract.fields import RuleBasedFieldExtractor
    from labelextract.preprocessing import PillowPreprocessor, PreprocessingConfig

    return ExtractionPipeline(
        name=NAME,
        version=BASELINE_VERSION,
        ocr_engine=TesseractOcrEngine(
            TesseractOptions(page_segmentation_mode=6, engine_mode=3)
        ),
        preprocessor=PillowPreprocessor(
            PreprocessingConfig(min_dimension=None, max_dimension=None)
        ),
        field_extractor=RuleBasedFieldExtractor(),
    )
