"""A pipeline that runs end to end without performing any real recognition.

Purpose
-------
It lets the team verify the whole path - upload, validation, extraction run,
field storage, compliance check, API response, UI rendering - before any OCR
engine is chosen, without anybody having to invent text to make it work.

It is NOT an OCR engine. It reads no pixels. It always returns zero text blocks
and zero fields, with `ExtractionStatus.EMPTY` and `is_placeholder=True`.

We publish no OCR accuracy, character error rate, or field-extraction F1 for
this project, because none have been measured. Replacing this placeholder is
the job of `feature/ocr-processing`.
"""

from __future__ import annotations

from labelextract.contracts import ImageRef, OcrResult
from labelextract.exceptions import InvalidImageError
from labelextract.interfaces import OcrEngine
from labelextract.pipeline import ExtractionPipeline

NAME = "null-engine"
VERSION = "0.1.0"

PLACEHOLDER_REASON = (
    "No OCR engine is installed. This run produced no text and carries no "
    "information about what is printed on the package."
)


class NullOcrEngine(OcrEngine):
    """Returns an empty result for every image, without decoding it.

    It still checks that the file exists and is non-empty, so that a broken
    storage path fails here - loudly, at the wiring stage - rather than looking
    like "the package had no text on it".
    """

    name = NAME
    version = VERSION

    @property
    def is_placeholder(self) -> bool:
        return True

    def recognise(self, image: ImageRef) -> OcrResult:
        if not image.path.exists():
            raise InvalidImageError(f"Image file does not exist: {image.path}")
        if image.path.stat().st_size == 0:
            raise InvalidImageError(f"Image file is empty: {image.path}")

        return OcrResult(
            blocks=(),
            raw={
                "placeholder": True,
                "reason": PLACEHOLDER_REASON,
                # Echoing what the backend measured makes it visible in the UI
                # that the file was read, even though nothing was recognised.
                "observed_format": image.image_format,
                "observed_size_bytes": image.size_bytes,
                "observed_dimensions": (
                    None
                    if image.width is None or image.height is None
                    else [image.width, image.height]
                ),
            },
        )


def build_pipeline() -> ExtractionPipeline:
    """Factory used by `labelextract.registry`.

    No field extractor is configured: with no recognised text there is nothing
    to interpret, and attaching one would only obscure that.
    """
    return ExtractionPipeline(
        name=NAME,
        version=VERSION,
        ocr_engine=NullOcrEngine(),
        preprocessor=None,
        field_extractor=None,
    )
