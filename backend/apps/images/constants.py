"""Allowlists for image ingestion.

Everything here is an allowlist, never a denylist. A denylist of "bad"
extensions is a list of the attacks someone already thought of; an allowlist of
three formats is a list of what we can actually process.

The three formats are the ones OCR engines universally accept. GIF, TIFF, BMP
and SVG are excluded on purpose: SVG in particular is an XML document that can
carry script and external entity references, and is not an image in any sense
useful to us.
"""

from pathlib import PurePosixPath

#: Canonical format name -> the extension we store the file under.
ALLOWED_FORMATS: dict[str, str] = {
    "jpeg": ".jpg",
    "png": ".png",
    "webp": ".webp",
}

#: Extensions a client may send, mapped to the canonical format name.
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
}

#: Content types a client may declare. The declared type is checked but never
#: trusted on its own - the file is decoded to confirm what it really is.
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",  # non-standard, but sent by some mobile browsers
    "image/png": "png",
    "image/webp": "webp",
}

#: Pillow's format identifier -> our canonical format name. Pillow reports the
#: format it actually decoded, which is the authoritative answer.
PILLOW_FORMAT_MAP: dict[str, str] = {
    "JPEG": "jpeg",
    "PNG": "png",
    "WEBP": "webp",
}

#: Reject images smaller than this in either dimension. An image this small
#: cannot carry legible label text, so accepting it only produces a confusing
#: empty extraction later.
MIN_IMAGE_DIMENSION = 32


def extension_for_upload(filename: str) -> str:
    """Return the storage extension for `filename`.

    Falls back to `.jpg` for an unrecognised extension. That is safe because
    `validators.validate_image_upload` has already rejected disallowed formats
    by the time a file is stored - this is only about naming the stored blob,
    and the authoritative format lives in `ProductImage.image_format`.
    """
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    canonical = ALLOWED_EXTENSIONS.get(suffix)
    if canonical is None:
        return ".jpg"
    return ALLOWED_FORMATS[canonical]
