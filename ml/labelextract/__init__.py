"""labelextract - extraction contracts and OCR/ML interfaces.

This package defines *what an extraction result looks like* and *what an OCR or
field-extraction implementation must provide*. It contains no trained models
and performs no real recognition of its own.

The Django backend depends on this package's public API only. It must never
import from `labelextract.baseline` or from a concrete engine module directly -
implementations are resolved at runtime through `registry`.
"""

from labelextract.contracts import (
    BoundingBox,
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    ImageRef,
    LabelFieldKey,
    OcrResult,
    TextBlock,
    UnreadDeclaration,
)
from labelextract.exceptions import (
    EngineNotAvailableError,
    FieldExtractionError,
    ImageTooLargeError,
    InvalidImageError,
    LabelExtractError,
    OcrFailureError,
    PipelineNotFoundError,
    PreprocessingError,
    UnsupportedImageFormatError,
)
from labelextract.interfaces import FieldExtractor, ImagePreprocessor, OcrEngine
from labelextract.pipeline import ExtractionPipeline

__version__ = "0.1.0"

__all__ = [
    "BoundingBox",
    "EngineNotAvailableError",
    "ExtractedField",
    "ExtractionPipeline",
    "ExtractionResult",
    "ExtractionStatus",
    "FieldExtractionError",
    "FieldExtractor",
    "ImagePreprocessor",
    "ImageRef",
    "ImageTooLargeError",
    "InvalidImageError",
    "LabelExtractError",
    "LabelFieldKey",
    "OcrEngine",
    "OcrFailureError",
    "OcrResult",
    "PipelineNotFoundError",
    "PreprocessingError",
    "TextBlock",
    "UnreadDeclaration",
    "UnsupportedImageFormatError",
    "__version__",
]
