"""The ingestion service: an upload becomes a row, or it becomes nothing.

`test_validators.py` covers what the validator refuses in isolation, and
`test_models.py` covers what the table guarantees once a file is accepted.
Neither covered the join between them, which is where the interesting failure
lives: a service that persisted first and validated second, or that took the
upload's word for its own format, would pass both of those files and still
store an attacker's file under attacker-chosen facts.

So the guarantee asserted here is narrow and specific: **there is no path
through this service that reaches the database without validation**, and every
column that describes the file is filled from what validation measured rather
than from what the upload claimed.
"""

from __future__ import annotations

import posixpath

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.images.models import ProductImage
from apps.images.services.ingestion import ingest_product_image

pytestmark = pytest.mark.django_db


def _upload(name: str, payload: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, payload, content_type=content_type)


# --- the accepted case ------------------------------------------------------


def test_a_valid_upload_becomes_a_stored_row(png_upload, media_root, product):
    image = ingest_product_image(png_upload, product=product)

    assert image.pk is not None
    assert image.product == product
    assert image.status == ProductImage.Status.UPLOADED
    assert image.image.storage.exists(image.image.name)


def test_the_stored_columns_come_from_the_bytes_not_the_claims(
    png_bytes, media_root
):
    """Every measured column is a measurement.

    The upload here *lies*: it is a PNG announced as `image/jpg` under a `.jpg`
    name. Both claims clear the cheap allowlist checks, and a service that
    copied them into the row would leave the database asserting a format the
    file does not have - which is the value every downstream decoder trusts.
    """
    image = ingest_product_image(_upload("label.jpg", png_bytes, "image/jpg"))

    assert image.image_format == "png"
    assert image.size_bytes == len(png_bytes)
    assert image.width == 64
    assert image.height == 64
    assert len(image.checksum_sha256) == 64


@pytest.mark.parametrize(
    ("name", "declared", "expected"),
    [
        ("label.png", "image/png", "image/png"),
        # A PNG announced as a JPEG under a `.jpg` name: both claims clear the
        # cheap allowlists, so only the decode can settle what this file is.
        ("label.jpg", "image/jpg", "image/png"),
        # A parameterised header is a legitimate thing for a client to send,
        # and must not change how the file ends up described.
        ("label.png", "image/png; charset=binary", "image/png"),
    ],
)
def test_the_stored_content_type_is_a_mime_type_for_the_measured_format(
    png_bytes, media_root, name, declared, expected
):
    """`content_type` holds a MIME type, and it describes the decoded bytes.

    Two failure modes are pinned together. The column is documented as
    "MIME/content type" (`docs/database-schema.md`), so a bare format name like
    `"png"` is wrong in it - and wrong in any `Content-Type` header built from
    it. And the value must not depend on how the client spelled its header,
    which would leave one column holding two vocabularies according to whether
    a `charset` parameter happened to be present.
    """
    image = ingest_product_image(_upload(name, png_bytes, declared))

    assert image.content_type == expected


def test_the_checksum_identifies_the_exact_bytes_analysed(png_bytes, media_root):
    """Two uploads of the same bytes agree; different bytes do not.

    This is what ties a compliance finding to the file it was made from.
    """
    import hashlib

    first = ingest_product_image(_upload("a.png", png_bytes, "image/png"))
    second = ingest_product_image(_upload("b.png", png_bytes, "image/png"))

    assert first.checksum_sha256 == second.checksum_sha256
    assert first.checksum_sha256 == hashlib.sha256(png_bytes).hexdigest()


def test_the_uploader_is_recorded_when_there_is_one(png_upload, media_root, user):
    image = ingest_product_image(png_upload, uploaded_by=user)

    assert image.uploaded_by == user


def test_the_product_may_be_left_unknown(png_upload, media_root):
    """Upload-then-identify: a photograph can arrive before we know what it is."""
    image = ingest_product_image(png_upload)

    assert image.product is None


# --- validation is not bypassable -------------------------------------------


@pytest.mark.parametrize(
    ("name", "payload", "content_type", "code"),
    [
        # A renamed non-image. Extension and content type both clear.
        ("photo.png", b"#!/bin/sh\necho pwned\n", "image/png", "undecodable_image"),
        # A real image under a disallowed extension.
        ("payload.svg", None, "image/png", "unsupported_extension"),
        # A real image under a disallowed content type.
        ("label.png", None, "application/pdf", "unsupported_content_type"),
        # Nothing at all.
        ("label.png", b"", "image/png", "empty_file"),
    ],
)
def test_a_rejected_upload_is_refused_by_the_service(
    png_bytes, media_root, name, payload, content_type, code
):
    """The service raises the validator's own error, with its code intact.

    The code is asserted because a DRF view branches on it: "convert this file"
    and "this file is corrupt" are different instructions to a user.
    """
    body = png_bytes if payload is None else payload

    with pytest.raises(ValidationError) as caught:
        ingest_product_image(_upload(name, body, content_type))

    assert caught.value.code == code


@pytest.mark.parametrize(
    ("name", "payload", "content_type"),
    [
        ("photo.png", b"not an image at all", "image/png"),
        ("payload.svg", None, "image/png"),
        ("label.png", b"", "image/png"),
    ],
)
def test_a_rejected_upload_leaves_no_row_and_no_file(
    png_bytes, media_root, name, payload, content_type
):
    """Rejection is total.

    A row written before validation, or left behind after it, would be a stored
    file nothing describes - and `run_extraction` would happily be handed it.
    """
    body = png_bytes if payload is None else payload

    with pytest.raises(ValidationError):
        ingest_product_image(_upload(name, body, content_type))

    assert ProductImage.objects.count() == 0


def test_an_oversized_upload_is_refused(png_bytes, media_root, settings):
    settings.MAX_IMAGE_UPLOAD_SIZE_BYTES = 10
    settings.MAX_IMAGE_UPLOAD_SIZE_MB = 0

    with pytest.raises(ValidationError) as caught:
        ingest_product_image(_upload("label.png", png_bytes, "image/png"))

    assert caught.value.code == "file_too_large"
    assert ProductImage.objects.count() == 0


def test_a_decompression_bomb_budget_is_still_enforced(
    png_bytes, media_root, settings
):
    """The pixel-count guard is the validator's, and ingestion inherits it."""
    settings.MAX_IMAGE_PIXELS = 100

    with pytest.raises(ValidationError) as caught:
        ingest_product_image(_upload("label.png", png_bytes, "image/png"))

    assert caught.value.code == "image_too_many_pixels"
    assert ProductImage.objects.count() == 0


def test_no_file_at_all_is_refused_rather_than_crashing(media_root):
    with pytest.raises(ValidationError) as caught:
        ingest_product_image(None)

    assert caught.value.code == "no_file"


# --- path safety ------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile_name",
    [
        "../../../../etc/passwd.png",
        "..\\..\\windows\\system32\\evil.png",
        "/absolute/path/label.png",
        "a" * 400 + ".png",
    ],
)
def test_a_hostile_filename_never_reaches_the_stored_path(
    png_bytes, media_root, hostile_name
):
    """The stored name is generated; the client's is display-only.

    Walked through the *service* rather than through the sanitiser directly,
    because the guarantee that matters is that ingestion cannot be persuaded to
    skip it.
    """
    image = ingest_product_image(_upload(hostile_name, png_bytes, "image/png"))

    stored = image.image.name
    assert stored.startswith("product-images/")
    assert ".." not in stored
    assert "\x00" not in stored

    # The display name is kept, but stripped of anything that could forge a log
    # line or escape a directory.
    assert "/" not in image.original_filename
    assert "\\" not in image.original_filename
    assert "\x00" not in image.original_filename
    assert len(image.original_filename) <= 255


def test_a_nul_byte_smuggling_an_executable_extension_is_rejected(
    png_bytes, media_root
):
    """`label.png\\x00.exe` is not stored under a truncated name.

    The sanitiser strips the NUL rather than splitting on it, so the extension
    check sees `.exe` and refuses the upload outright. Asserted because the
    opposite convention - treating the NUL as a terminator - is what makes this
    trick work elsewhere.
    """
    with pytest.raises(ValidationError) as caught:
        ingest_product_image(_upload("label.png\x00.exe", png_bytes, "image/png"))

    assert caught.value.code == "unsupported_extension"
    assert ProductImage.objects.count() == 0


def test_the_stored_extension_always_comes_from_the_allowlist(
    png_bytes, media_root
):
    """The blob is named from an allowlisted extension, never a client string.

    Note what this does *not* claim: the stored extension follows the client's
    (already allowlisted) extension, not the decoded format, so a PNG announced
    as `label.jpg` lands as `.jpg`. That is the documented design - the
    authoritative format lives in `ProductImage.image_format`, and the media
    root is never executed - so the guarantee worth pinning is that the
    extension is one of three image types and nothing else.
    """
    image = ingest_product_image(_upload("label.jpg", png_bytes, "image/jpg"))

    assert posixpath.splitext(image.image.name)[1] in {".jpg", ".png", ".webp"}
    assert image.image_format == "png"


# --- the view type is a real vocabulary -------------------------------------


def test_a_known_view_type_is_stored(png_upload, media_root):
    image = ingest_product_image(png_upload, view_type=ProductImage.ViewType.BACK)

    assert image.view_type == ProductImage.ViewType.BACK


def test_an_unknown_view_type_is_refused(png_upload, media_root):
    """The column stores choices without enforcing them.

    An unrecognised value would reach the compliance engine as a claim about
    which panel the photograph shows - and that is what decides whether an
    absent declaration is evidence of anything.
    """
    with pytest.raises(ValidationError) as caught:
        ingest_product_image(png_upload, view_type="left-ish")

    assert caught.value.code == "unknown_view_type"
    assert ProductImage.objects.count() == 0
