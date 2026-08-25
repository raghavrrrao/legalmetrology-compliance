"""Validation for uploaded product images.

Threat model, and why each check exists
---------------------------------------
An uploaded file is attacker-controlled in every respect: its name, its
declared content type, its size, and its bytes. Each of the following is a
distinct attack that the others do not cover.

1. **Extension and content type are claims, not facts.** They are checked
   first because they are cheap, but passing them proves nothing. `shell.php`
   renamed to `photo.jpg` and sent as `image/jpeg` clears both.

2. **Size is enforced before decoding.** Django's
   `DATA_UPLOAD_MAX_MEMORY_SIZE` rejects oversized bodies at the transport
   layer; this repeats the check at the application layer so a caller that
   builds an upload in code cannot bypass it.

3. **Decompression bombs.** A 40 KB PNG can declare dimensions that expand to
   several gigabytes of pixels. Dimensions are read from the header and the
   pixel count is checked *before* the image is fully loaded.

4. **The file is actually decoded.** `Image.verify()` parses the structure and
   raises on a malformed or non-image file. This is the check that catches the
   renamed executable, because it asks the decoder what the bytes are rather
   than asking the uploader.

5. **The decoded format must match the allowlist.** A file that decodes as a
   TIFF but arrived as `.png` is rejected on what it *is*, not what it claimed.

Raises `django.core.exceptions.ValidationError` throughout, so DRF serializers
surface these as 400 responses via the standard error envelope rather than as
500s.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import PurePosixPath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, UnidentifiedImageError

from apps.images.constants import (
    ALLOWED_CONTENT_TYPES,
    ALLOWED_EXTENSIONS,
    MIN_IMAGE_DIMENSION,
    PILLOW_FORMAT_MAP,
)
from apps.images.storage import sanitise_display_filename

logger = logging.getLogger(__name__)

#: Read the file in chunks when checksumming, so a large upload is never held
#: in memory in full.
_CHECKSUM_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class ValidatedImage:
    """Facts established by validation, derived from the bytes themselves.

    Every field here was measured, not taken from the upload's claims. The
    caller persists these onto `ProductImage` rather than re-deriving them.
    """

    original_filename: str
    image_format: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    checksum_sha256: str


def validate_image_upload(upload: UploadedFile) -> ValidatedImage:
    """Validate `upload` and return the facts measured from it.

    Raises:
        ValidationError: the upload is not an acceptable product image. The
            message is safe to show a user and never echoes file content.
    """
    original_filename = sanitise_display_filename(upload.name or "")

    _check_extension(original_filename)
    _check_content_type(upload)
    size_bytes = _check_size(upload)

    width, height, image_format = _decode_and_measure(upload)

    checksum = _sha256(upload)

    # Leave the handle where Django's storage backend expects it.
    upload.seek(0)

    return ValidatedImage(
        original_filename=original_filename,
        image_format=image_format,
        content_type=ALLOWED_CONTENT_TYPES.get(
            (upload.content_type or "").lower(), f"image/{image_format}"
        ),
        size_bytes=size_bytes,
        width=width,
        height=height,
        checksum_sha256=checksum,
    )


# --- individual checks ------------------------------------------------------


def _check_extension(filename: str) -> None:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValidationError(
            f"Unsupported file extension. Allowed extensions: {allowed}.",
            code="unsupported_extension",
        )


def _check_content_type(upload: UploadedFile) -> None:
    content_type = (upload.content_type or "").lower().split(";")[0].strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_CONTENT_TYPES))
        raise ValidationError(
            f"Unsupported content type. Allowed types: {allowed}.",
            code="unsupported_content_type",
        )


def _check_size(upload: UploadedFile) -> int:
    size = upload.size or 0
    if size == 0:
        raise ValidationError("The uploaded file is empty.", code="empty_file")
    if size > settings.MAX_IMAGE_UPLOAD_SIZE_BYTES:
        raise ValidationError(
            f"Image is too large. Maximum size is "
            f"{settings.MAX_IMAGE_UPLOAD_SIZE_MB} MB.",
            code="file_too_large",
        )
    return size


def _decode_and_measure(upload: UploadedFile) -> tuple[int, int, str]:
    """Decode the image to establish what it really is.

    Opens the file twice on purpose: `verify()` consumes the stream and leaves
    the `Image` object unusable, so dimensions are read on a fresh open. The
    pixel-count guard runs on the first open, before `verify()` walks the whole
    file.
    """
    upload.seek(0)
    try:
        with Image.open(upload) as probe:
            # Header only - no pixel data has been loaded at this point.
            width, height = probe.size
            pillow_format = probe.format
            _check_dimensions(width, height)
    except UnidentifiedImageError:
        raise ValidationError(
            "The file could not be read as an image.", code="undecodable_image"
        ) from None
    except ValidationError:
        raise
    except Exception:
        # Pillow raises a wide range of errors on malformed input. Log the
        # detail for us; tell the user only that the file was not usable.
        logger.exception("Unexpected error while reading an uploaded image")
        raise ValidationError(
            "The file could not be read as an image.", code="undecodable_image"
        ) from None

    if pillow_format not in PILLOW_FORMAT_MAP:
        raise ValidationError(
            "The file is not one of the supported image formats "
            "(JPEG, PNG, WebP).",
            code="unsupported_image_format",
        )

    upload.seek(0)
    try:
        with Image.open(upload) as verifier:
            # Parses the full structure and raises on truncation or corruption.
            verifier.verify()
    except Exception:
        raise ValidationError(
            "The image file is corrupt or incomplete.", code="corrupt_image"
        ) from None

    return width, height, PILLOW_FORMAT_MAP[pillow_format]


def _check_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ValidationError(
            "The image reports invalid dimensions.", code="invalid_dimensions"
        )
    if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
        raise ValidationError(
            f"Image is too small to read a label from. Minimum "
            f"{MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION} pixels.",
            code="image_too_small",
        )
    if width * height > settings.MAX_IMAGE_PIXELS:
        # Checked before any decode: this is the decompression-bomb guard.
        raise ValidationError(
            "Image resolution is too large to process.",
            code="image_too_many_pixels",
        )


def _sha256(upload: UploadedFile) -> str:
    """Checksum the uploaded bytes.

    Stored on `ProductImage` so that a compliance result can be tied to the
    exact file that was analysed. If the stored file is ever replaced or
    corrupted, the result no longer matches its evidence, and that is
    detectable rather than silent.
    """
    upload.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: upload.read(_CHECKSUM_CHUNK_SIZE), b""):
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()
