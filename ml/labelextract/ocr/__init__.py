"""Concrete OCR engines.

One engine so far - Tesseract. It sits behind `interfaces.OcrEngine`, so a
later switch to PaddleOCR, a fine-tuned recogniser, or a cloud API changes the
contents of this package and nothing else in the repository.

Importing this package does not import pytesseract. Engines resolve their
dependencies on first use and report a missing one as
`EngineNotAvailableError`, so `labelextract`'s contracts stay installable with
no OCR stack present - which is what lets the unit tests run anywhere.
"""

from labelextract.ocr.tesseract import (
    NAME,
    VERSION,
    PytesseractRunner,
    TesseractOcrEngine,
    TesseractOptions,
    TesseractRunner,
    build_pipeline,
)

__all__ = [
    "NAME",
    "VERSION",
    "PytesseractRunner",
    "TesseractOcrEngine",
    "TesseractOptions",
    "TesseractRunner",
    "build_pipeline",
]
