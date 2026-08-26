"""Abstract interfaces that OCR/ML implementations must satisfy.

Three separate responsibilities, three separate interfaces. Keeping them apart
matters because they fail differently and improve independently: better
preprocessing does not make field extraction smarter, and a better OCR engine
does not know what a "net quantity" is.

    ImagePreprocessor   pixels        -> pixels        (deskew, denoise, crop)
    OcrEngine           pixels        -> text + boxes  (recognition)
    FieldExtractor      text + boxes  -> declarations  (interpretation)

Deliberately NOT defined here
-----------------------------
`ProductClassifier` (predicting a commodity category from the image) is a real
future responsibility, but nothing in the base calls it, and an interface with
no caller and no implementation is a guess about a signature we have not had to
design yet. `feature/product-classification` adds it.

Label region detection is likewise absent: whether it is a preprocessing step
or part of the OCR engine depends on which engine is chosen, and committing to
one answer now would constrain that choice for no benefit.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from labelextract.contracts import ExtractedField, ImageRef, OcrResult


class _Component(ABC):
    """Shared metadata for every pluggable extraction component."""

    #: Stable identifier, e.g. "tesseract". Persisted on the extraction run.
    name: str = "unnamed"
    #: Implementation version, e.g. "5.3.0". Persisted alongside `name`.
    version: str = "0.0.0"

    @property
    def is_placeholder(self) -> bool:
        """True when this component is wiring only and does no real work.

        Implementations backed by a real engine leave this False. The value
        travels to the API response so placeholder output is never displayed as
        a genuine reading.
        """
        return False

    def warmup(self) -> None:
        """Optional hook to load models/binaries before the first request.

        Default is a no-op. Implementations that load large models should do so
        here rather than in `__init__`, so the cost is paid once at startup
        instead of on a user's first upload.
        """


class ImagePreprocessor(_Component):
    """Prepares a raw photograph for recognition.

    Typical work: deskew, correct perspective, denoise, boost contrast, convert
    colour space. Implementations return a path to the processed image; they
    must not overwrite the original, which is retained as evidence.
    """

    @abstractmethod
    def process(self, image: ImageRef) -> ImageRef:
        """Return a new `ImageRef` for the preprocessed image.

        Raises:
            InvalidImageError: the image cannot be decoded.
            ImageTooLargeError: the image exceeds the processing budget.
            PreprocessingError: a transform failed on a decodable image.
        """

    def release(self, processed: ImageRef) -> None:
        """Discard an intermediate produced by `process`.

        The pipeline calls this once recognition and field extraction are done,
        so a long-running server does not accumulate a preprocessed copy of
        every upload on disk. The original is never passed here.

        Default is a no-op, for preprocessors that write nothing. An
        implementation must never raise: failing to delete a temporary file is
        an operational annoyance, not a reason to lose an extraction result.

        `ExtractionPipeline` guards the call anyway and logs anything that
        escapes, so a preprocessor that breaks this rule costs a leftover file
        rather than a lost result. Treat that as a safety net for a bug, not as
        permission to raise: only the implementation knows which failures are
        worth reporting, and a swallowed exception is invisible to it.
        """


class OcrEngine(_Component):
    """Recognises text and its position on the image.

    An engine reports *what characters it saw and where*. It must not attempt
    to interpret meaning - that is `FieldExtractor`'s job. Engines that cannot
    report per-block confidence leave `TextBlock.confidence` as None rather
    than substituting a placeholder number.
    """

    @abstractmethod
    def recognise(self, image: ImageRef) -> OcrResult:
        """Recognise text on `image`.

        Returning an empty `OcrResult` is valid and means "no text found" -
        a blurred or blank photograph, not an error.

        Raises:
            InvalidImageError: the image cannot be decoded.
            EngineNotAvailableError: the engine binary or model is missing.
        """


class FieldExtractor(_Component):
    """Locates label declarations within recognised text.

    This is where "MRP Rs. 250" becomes
    `ExtractedField(key=RETAIL_SALE_PRICE, raw_value="MRP Rs. 250")`.

    An extractor reports only what it found. It must never emit a field for a
    declaration it did not locate in order to "complete" a set - a missing
    field is meaningful input to the compliance engine, and inventing one would
    silently turn a non-compliant package into a compliant one.
    """

    @abstractmethod
    def extract(self, ocr: OcrResult, image: ImageRef) -> tuple[ExtractedField, ...]:
        """Return the declarations found in `ocr`. May be empty."""
