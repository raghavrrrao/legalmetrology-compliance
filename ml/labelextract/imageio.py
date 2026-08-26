"""Filesystem checks shared by every stage that opens an image.

Both the preprocessor and the OCR engine need the same guarantee before they
touch a file, and both are entry points: the pipeline may be configured without
a preprocessor, so neither can rely on the other having checked. One
implementation rather than two keeps the failure identical whichever stage
reaches the file first.

**Nothing in this module imports Pillow.** That is the point of it. It is the
zero-dependency half of the input boundary: whether a path is readable, and
whether its bytes even claim to be an image we support, are questions the
standard library can answer. Only *measuring* an image - its exact dimensions -
needs a decoder, and that is left to the stages that have one.

Keeping the split here rather than inside each caller is what lets
`labelextract.cli` reject an empty file or a renamed text file identically with
or without the optional `[ocr]` extra installed.
"""

from __future__ import annotations

from pathlib import Path

from labelextract.contracts import ImageRef
from labelextract.exceptions import InvalidImageError

#: Leading bytes that identify each format in `SUPPORTED_FORMATS`, mapped to
#: our canonical format name. These are the formats the upload validator
#: allows, so the two ends of the system agree on what an image is.
#:
#: Magic bytes are a claim about structure, not proof the file decodes - a
#: truncated PNG still starts with the PNG signature. They are enough to reject
#: a renamed script or document without a decoder, which is all this is for.
#: The authoritative answer still comes from Pillow in `preprocessing`.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_RIFF_SIGNATURE = b"RIFF"
_WEBP_TAG = b"WEBP"

#: Enough bytes to cover the longest signature check (WebP's tag at offset 8).
_SIGNATURE_BYTES = 12


def readable_file(path: Path) -> Path:
    """Resolve `path` and confirm it is a non-empty regular file.

    `resolve()` collapses any `..` before the file is opened. Paths normally
    originate in our own storage layer rather than from a user, so that is
    defence in depth - but `labelextract.cli` is also an entry point, and there
    the path does come from a person.

    An empty or missing file is `InvalidImageError`, never an empty
    `OcrResult`. A broken storage path must be visible as a failure; reporting
    it as "no text found" would make it indistinguishable from a blank label.

    Raises:
        InvalidImageError: the path is missing, not a file, or empty.
    """
    resolved = path.resolve()
    if not resolved.exists():
        raise InvalidImageError(f"Image file does not exist: {resolved}")
    if not resolved.is_file():
        raise InvalidImageError(f"Not a regular file: {resolved}")
    if resolved.stat().st_size == 0:
        raise InvalidImageError(f"Image file is empty: {resolved}")
    return resolved


def readable_path(image: ImageRef) -> Path:
    """`readable_file` for an `ImageRef`. The form the pipeline stages use."""
    return readable_file(image.path)


def sniff_image_format(path: Path) -> str | None:
    """Return the canonical format the file's leading bytes claim, or None.

    None means "these bytes are not one of the formats we accept" - a renamed
    text file, a PDF, a TIFF. It is deliberately conservative: it never guesses
    from the filename extension, which is a claim by whoever named the file.

    Raises:
        InvalidImageError: the file could not be read at all.
    """
    try:
        with path.open("rb") as handle:
            header = handle.read(_SIGNATURE_BYTES)
    except OSError as exc:
        raise InvalidImageError(
            f"Image file could not be read: {exc.__class__.__name__}"
        ) from exc

    if header.startswith(_PNG_SIGNATURE):
        return "png"
    if header.startswith(_JPEG_SIGNATURE):
        return "jpeg"
    if header.startswith(_RIFF_SIGNATURE) and header[8:12] == _WEBP_TAG:
        return "webp"
    return None
