"""Data contracts exchanged between the backend and any OCR/ML implementation.

These types are the stable boundary. The OCR engine can be swapped - Tesseract,
PaddleOCR, a cloud API, a fine-tuned vision model - without the Django backend
changing, as long as it keeps producing these structures.

Two rules are enforced throughout:

1. Every value a real model would have to *measure* (confidence, bounding box,
   recognised text) is Optional and defaults to None. An implementation that
   cannot compute a value reports None. It never invents one.

2. Nothing in this module makes a legal claim. `LabelFieldKey` is a vocabulary
   of things that appear printed on packaging. It says nothing about whether a
   declaration is legally required - that is decided by the `rules` app against
   verified source material.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class LabelFieldKey(str, Enum):
    """Vocabulary of declarations that may be printed on a package label.

    IMPORTANT - this is an extraction vocabulary, NOT a legal requirement list.

    A key existing here means only "our extractor knows how to look for this on
    a package". It does NOT mean the declaration is mandatory, nor that it is
    mandatory for a particular commodity. Applicability and obligation are
    determined by `ComplianceRule` rows loaded from verified sources, and this
    project ships zero such rules until they have been checked against the
    authoritative text of the Legal Metrology (Packaged Commodities) Rules,
    2011.

    Adding a key here is a change to what we can read off a package. It is
    never, by itself, a change to what the system requires.
    """

    MANUFACTURER_NAME = "manufacturer_name"
    PACKER_NAME = "packer_name"
    IMPORTER_NAME = "importer_name"
    MANUFACTURER_ADDRESS = "manufacturer_address"
    COMMON_OR_GENERIC_NAME = "common_or_generic_name"
    NET_QUANTITY = "net_quantity"
    RETAIL_SALE_PRICE = "retail_sale_price"
    UNIT_SALE_PRICE = "unit_sale_price"
    DATE_OF_MANUFACTURE = "date_of_manufacture"
    DATE_OF_PACKING = "date_of_packing"
    DATE_OF_IMPORT = "date_of_import"
    BEST_BEFORE = "best_before"
    CONSUMER_CARE_CONTACT = "consumer_care_contact"
    COUNTRY_OF_ORIGIN = "country_of_origin"
    BATCH_NUMBER = "batch_number"
    OTHER = "other"


class ExtractionStatus(str, Enum):
    """Whether the pipeline produced usable output."""

    #: The pipeline ran and produced extracted text.
    COMPLETED = "completed"
    #: The pipeline ran but recognised nothing usable (blurred, blank, no text).
    #: Not an error - a legitimate outcome the compliance engine must handle.
    EMPTY = "empty"
    #: The pipeline could not run. See ExtractionResult.error_code.
    FAILED = "failed"


@dataclass(frozen=True)
class ImageRef:
    """A validated, on-disk image handed to the extraction layer.

    The backend validates and stores the file before building this object. The
    extraction layer still makes no assumption that the pixel content is
    meaningful - only that the path is readable.

    `width`/`height` are None when the backend could not determine them.
    """

    path: Path
    image_format: str
    size_bytes: int
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise TypeError("ImageRef.path must be a pathlib.Path")


@dataclass(frozen=True)
class BoundingBox:
    """Pixel-space region of the source image, origin at top-left.

    Carried so the UI can highlight *where on the package* a declaration was
    read from. That is what turns a compliance result into evidence rather than
    an unexplained verdict.
    """

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("BoundingBox width and height must be positive")
        if self.x < 0 or self.y < 0:
            raise ValueError("BoundingBox x and y must be non-negative")

    def as_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class TextBlock:
    """One contiguous piece of text recognised on the image."""

    text: str
    box: BoundingBox | None = None
    #: OCR engine confidence in [0.0, 1.0], or None when the engine does not
    #: report one. Never fabricate a value to fill this in.
    confidence: float | None = None

    def __post_init__(self) -> None:
        _check_unit_interval("confidence", self.confidence)


@dataclass(frozen=True)
class OcrResult:
    """Raw recognition output, before any interpretation of meaning."""

    blocks: tuple[TextBlock, ...] = ()
    #: Engine-specific diagnostics, persisted verbatim as JSON for auditing and
    #: for re-running field extraction without re-running OCR.
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        """All recognised text joined by newlines, in engine order."""
        return "\n".join(block.text for block in self.blocks)


@dataclass(frozen=True)
class ExtractedField:
    """One label declaration located in the recognised text.

    This is an *observation*: "we read this string, here, with this confidence".
    Whether the value is correct, or whether it was required at all, is decided
    later by the compliance engine.
    """

    key: LabelFieldKey
    #: Text exactly as recognised. Never cleaned up in place - normalisation
    #: produces `normalized_value` and leaves the raw reading auditable.
    raw_value: str
    #: Structured interpretation, e.g. {"quantity": 500, "unit": "g"}.
    #: None when no normaliser exists for this key yet.
    normalized_value: Mapping[str, Any] | None = None
    confidence: float | None = None
    box: BoundingBox | None = None

    def __post_init__(self) -> None:
        _check_unit_interval("confidence", self.confidence)
        if not self.raw_value:
            raise ValueError("ExtractedField.raw_value must not be empty")


@dataclass(frozen=True)
class UnreadDeclaration:
    """A declaration's keyword was recognised; no value could be read for it.

    The case this exists for, seen on a real photograph: OCR returns the line
    `MRP` and nothing else, because the rest of that line was too foreshortened
    to recognise. The package plainly carries an MRP declaration - the keyword
    is right there - but its value is unknown.

    Without this, that outcome is indistinguishable from "this package declares
    no MRP at all". They are opposite findings: one is "photograph the panel
    again", the other is a potential violation. A compliance engine handed only
    an empty `fields` tuple cannot tell them apart, and would have to guess.

    **This is deliberately not an `ExtractedField`, and must never become one.**
    A presence check passes on any extracted field regardless of its
    uncertainty flag, so emitting a value-less field here would record the
    package as having declared something nobody could read - turning a possible
    violation into a pass. Absence of a field stays absence; this is a separate
    observation alongside it.

    It carries no value, because there is none. It makes no legal claim: that
    a keyword was printed says nothing about whether the declaration was
    required, correct, or complete.
    """

    key: LabelFieldKey
    #: The recognised line the keyword was found on, exactly as read.
    evidence_text: str
    #: Where that line sits on the source image, when the engine reported it.
    box: BoundingBox | None = None
    #: The engine's confidence in the evidence line, or None if unreported.
    confidence: float | None = None

    def __post_init__(self) -> None:
        _check_unit_interval("confidence", self.confidence)
        if not self.evidence_text.strip():
            # An observation with no evidence is not an observation. Reporting
            # "an MRP keyword was seen" without being able to show the line it
            # was seen on would be an unfalsifiable claim.
            raise ValueError("UnreadDeclaration requires the evidence line")

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe form, as persisted in run metadata."""
        return {
            "key": self.key.value,
            "evidence_text": self.evidence_text,
            "box": self.box.as_dict() if self.box else None,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ExtractionResult:
    """The complete structured result the backend persists.

    `is_placeholder=True` marks output produced by wiring code rather than a
    real OCR engine. The backend propagates the flag all the way to the API so
    the UI can never present placeholder output as a genuine reading.
    """

    status: ExtractionStatus
    engine_name: str
    engine_version: str
    processing_ms: int
    ocr: OcrResult = field(default_factory=OcrResult)
    fields: tuple[ExtractedField, ...] = ()
    is_placeholder: bool = False
    #: Set when status is FAILED. A stable string the backend can branch on.
    error_code: str | None = None
    error_message: str | None = None
    #: Timings, image dimensions, engine settings - anything useful for
    #: debugging that is not itself an extraction result.
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def field_for(self, key: LabelFieldKey) -> ExtractedField | None:
        """Return the first field extracted for `key`, or None if absent.

        Absence means "not found on this image", which is not the same as
        "not present on the package" - the photo may not show that panel. The
        compliance engine must treat the two differently.
        """
        for extracted in self.fields:
            if extracted.key is key:
                return extracted
        return None


def _check_unit_interval(name: str, value: float | None) -> None:
    if value is None:
        return
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{name} must be within [0.0, 1.0], got {value!r}")
