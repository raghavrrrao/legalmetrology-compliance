"""Image upload validation.

Each test corresponds to a distinct way an upload can be hostile or broken. The
important ones are the last group: an attacker controls the filename and the
declared content type, so validation must reach a verdict from the bytes.
"""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.images.storage import product_image_upload_path, sanitise_display_filename
from apps.images.validators import validate_image_upload
from conftest import make_png_bytes


def _upload(name: str, content: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=content_type)


# --- the happy path ---------------------------------------------------------


def test_valid_png_is_accepted_and_measured(png_bytes):
    result = validate_image_upload(_upload("label.png", png_bytes, "image/png"))

    assert result.image_format == "png"
    assert result.width == 64
    assert result.height == 64
    assert result.size_bytes == len(png_bytes)
    assert len(result.checksum_sha256) == 64


def test_checksum_is_of_the_actual_bytes(png_bytes):
    """The checksum ties a compliance result to the exact file analysed."""
    import hashlib

    result = validate_image_upload(_upload("label.png", png_bytes, "image/png"))
    assert result.checksum_sha256 == hashlib.sha256(png_bytes).hexdigest()


def test_file_pointer_is_left_at_the_start(png_bytes):
    """Django's storage backend reads from position 0 after validation."""
    upload = _upload("label.png", png_bytes, "image/png")
    validate_image_upload(upload)
    assert upload.tell() == 0


# --- claims that must not be trusted ----------------------------------------


def test_a_non_image_renamed_to_png_is_rejected():
    """The core check: extension and content type are claims, bytes are facts."""
    payload = b"#!/bin/sh\necho compromised\n"
    with pytest.raises(ValidationError) as exc:
        validate_image_upload(_upload("payload.png", payload, "image/png"))

    assert exc.value.code == "undecodable_image"


def test_html_disguised_as_an_image_is_rejected():
    payload = b"<html><script>alert(1)</script></html>"
    with pytest.raises(ValidationError):
        validate_image_upload(_upload("x.png", payload, "image/png"))


def test_truncated_image_is_rejected(png_bytes):
    """A valid header with a corrupt body must not pass as a usable image."""
    truncated = png_bytes[: len(png_bytes) // 2]
    with pytest.raises(ValidationError):
        validate_image_upload(_upload("label.png", truncated, "image/png"))


# --- allowlists -------------------------------------------------------------


@pytest.mark.parametrize("name", ["evil.svg", "doc.pdf", "archive.zip", "shell.php"])
def test_disallowed_extensions_are_rejected(name, png_bytes):
    with pytest.raises(ValidationError) as exc:
        validate_image_upload(_upload(name, png_bytes, "image/png"))
    assert exc.value.code == "unsupported_extension"


def test_disallowed_content_type_is_rejected(png_bytes):
    with pytest.raises(ValidationError) as exc:
        validate_image_upload(_upload("label.png", png_bytes, "application/pdf"))
    assert exc.value.code == "unsupported_content_type"


# --- size and resolution ----------------------------------------------------


def test_empty_file_is_rejected():
    with pytest.raises(ValidationError) as exc:
        validate_image_upload(_upload("label.png", b"", "image/png"))
    assert exc.value.code == "empty_file"


def test_oversized_file_is_rejected(settings, png_bytes):
    settings.MAX_IMAGE_UPLOAD_SIZE_BYTES = 10
    with pytest.raises(ValidationError) as exc:
        validate_image_upload(_upload("label.png", png_bytes, "image/png"))
    assert exc.value.code == "file_too_large"


def test_tiny_image_is_rejected():
    """Too small to carry legible label text; accepting it only wastes an OCR run."""
    tiny = make_png_bytes(width=8, height=8)
    with pytest.raises(ValidationError) as exc:
        validate_image_upload(_upload("label.png", tiny, "image/png"))
    assert exc.value.code == "image_too_small"


def test_decompression_bomb_is_rejected_by_pixel_count(settings, png_bytes):
    """A small file can declare dimensions that expand to gigabytes of pixels.

    The guard reads dimensions from the header and refuses before decoding.
    """
    settings.MAX_IMAGE_PIXELS = 100  # 64x64 = 4096 pixels
    with pytest.raises(ValidationError) as exc:
        validate_image_upload(_upload("label.png", png_bytes, "image/png"))
    assert exc.value.code == "image_too_many_pixels"


# --- filename handling ------------------------------------------------------


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("../../../etc/passwd", "passwd"),
        (r"C:\Users\victim\photo.jpg", "photo.jpg"),
        ("nested/dir/label.png", "label.png"),
        ("", "unnamed"),
        ("...", "unnamed"),
    ],
)
def test_display_filename_is_stripped_of_directories(supplied, expected):
    assert sanitise_display_filename(supplied) == expected


def test_control_characters_are_removed_from_display_filenames():
    """Control characters can forge log lines and corrupt terminal output."""
    assert sanitise_display_filename("label\x00\x1b[31m.png") == "label[31m.png"


def test_display_filename_length_is_capped():
    assert len(sanitise_display_filename("a" * 400 + ".png")) <= 255


def test_storage_path_ignores_the_supplied_filename():
    """The stored name is generated, so a hostile filename cannot pick the path."""
    path = product_image_upload_path(None, "../../../etc/passwd.png")

    assert path.startswith("product-images/")
    assert ".." not in path
    assert "passwd" not in path
    assert path.endswith(".png")


def test_storage_paths_are_unique_for_identical_filenames():
    """Two users uploading 'photo.jpg' must not overwrite each other."""
    first = product_image_upload_path(None, "photo.jpg")
    second = product_image_upload_path(None, "photo.jpg")
    assert first != second


def test_storage_extension_comes_from_an_allowlist():
    """An unrecognised extension never reaches the filesystem verbatim."""
    assert product_image_upload_path(None, "x.php").endswith(".jpg")
    assert product_image_upload_path(None, "x.jpeg").endswith(".jpg")
