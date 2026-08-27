"""Database guarantees for uploaded product photographs.

`test_validators.py` covers what the upload boundary refuses. This file covers
what the *table* guarantees once a file has been accepted: the storage path it
generates, the deletion behaviour that keeps analyses from outliving their
evidence, and the two fields that make a compliance result traceable back to
the exact bytes analysed.

The security-relevant guarantee here is the upload path. `original_filename`
holds a client-supplied string and is documented as display-only; the stored
name is generated. Nothing asserted that, and the difference between the two is
the difference between a display bug and a path traversal.
"""

from __future__ import annotations

import posixpath
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.images.models import ProductImage
from apps.images.storage import (
    MAX_DISPLAY_FILENAME_LENGTH,
    sanitise_display_filename,
)


# --- the stored path is generated, never taken from the client --------------


@pytest.mark.parametrize(
    "hostile_name",
    [
        "../../../../etc/passwd",
        "..\\..\\windows\\system32\\config\\sam",
        "/absolute/path/label.png",
        "label.png\x00.exe",
        "a" * 400 + ".png",
    ],
)
def test_a_hostile_filename_never_reaches_the_stored_path(
    db, product, png_bytes, media_root, hostile_name
):
    """The stored path is generated; the display name is sanitised on the way in.

    Every string here is a real attempt at escaping the media root, and each
    would be rejected by the *column* rather than the application if it arrived
    raw - a 500 instead of a validation error. It never arrives raw:
    `validate_image_upload` runs `sanitise_display_filename` first, which is
    what strips the directory components, the NUL byte and the excess length.
    This walks that same chain, so it fails if either half stops doing its job.
    """
    display_name = sanitise_display_filename(hostile_name)

    # The sanitiser's half of the contract: safe to store and safe to echo.
    assert "/" not in display_name and "\\" not in display_name
    assert "\x00" not in display_name
    assert len(display_name) <= MAX_DISPLAY_FILENAME_LENGTH

    image = ProductImage.objects.create(
        product=product,
        image=SimpleUploadedFile(hostile_name, png_bytes, content_type="image/png"),
        original_filename=display_name,
        content_type="image/png",
        image_format="png",
        size_bytes=len(png_bytes),
        width=64,
        height=64,
        checksum_sha256="0" * 64,
    )

    # The storage layer's half: the path owes nothing to the client's string.
    stored = image.image.name
    assert stored.startswith("product-images/")
    assert ".." not in stored
    assert not posixpath.isabs(stored)
    assert display_name not in stored


def test_the_display_filename_column_fits_everything_the_sanitiser_emits(db):
    """The sanitiser's cap and the column's width must agree.

    They are declared in different modules. If the cap ever exceeded the
    column, a long upload name would raise `DataError` from PostgreSQL - a 500
    on a valid upload, surfacing as "server error" rather than as anything a
    user could act on.
    """
    column = ProductImage._meta.get_field("original_filename").max_length
    assert MAX_DISPLAY_FILENAME_LENGTH <= column

    longest = sanitise_display_filename("a" * 1000 + ".png")
    assert len(longest) <= column


def test_the_stored_name_does_not_collide_for_two_identical_uploads(
    db, product, png_bytes, media_root
):
    """Two people photographing the same pack must not overwrite each other."""
    def upload():
        return ProductImage.objects.create(
            product=product,
            image=SimpleUploadedFile("label.png", png_bytes, content_type="image/png"),
            original_filename="label.png",
            content_type="image/png",
            image_format="png",
            size_bytes=len(png_bytes),
            width=64,
            height=64,
            checksum_sha256="0" * 64,
        )

    assert upload().image.name != upload().image.name


# --- traceability ------------------------------------------------------------


def test_the_checksum_ties_a_result_to_the_exact_bytes_analysed(product_image):
    """A compliance finding is about one specific file, and this is what says which.

    Without it, "this package was non-compliant" cannot be tied to the
    photograph it was concluded from, and a swapped file would be undetectable.
    """
    product_image.refresh_from_db()
    assert len(product_image.checksum_sha256) == 64


def test_measured_dimensions_are_stored_rather_than_recomputed(product_image):
    """Recorded at validation time, because the file may move to object storage."""
    product_image.refresh_from_db()
    assert (product_image.width, product_image.height) == (64, 64)
    assert product_image.size_bytes > 0
    # The format is what the decoder found, not what the client claimed.
    assert product_image.image_format == "png"


# --- upload-then-identify ----------------------------------------------------


def test_an_image_can_exist_before_its_product_is_known(db, png_bytes, media_root):
    """The real workflow is photograph first, identify second.

    Requiring a product up front would make the UI ask the question the user
    opened the app to answer.
    """
    image = ProductImage.objects.create(
        product=None,
        image=SimpleUploadedFile("label.png", png_bytes, content_type="image/png"),
        original_filename="label.png",
        content_type="image/png",
        image_format="png",
        size_bytes=len(png_bytes),
        width=64,
        height=64,
        checksum_sha256="0" * 64,
    )
    image.refresh_from_db()
    assert image.product is None
    assert image.status == ProductImage.Status.UPLOADED
    assert image.view_type == ProductImage.ViewType.UNSPECIFIED


def test_the_primary_key_is_a_uuid(product_image):
    """IDs appear in URLs; sequential ones would enumerate other users' uploads."""
    assert isinstance(product_image.pk, uuid.UUID)


# --- deletion behaviour ------------------------------------------------------


def test_deleting_a_product_removes_its_images(db, product, png_bytes, media_root):
    """Analyses must not outlive the product they describe."""
    ProductImage.objects.create(
        product=product,
        image=SimpleUploadedFile("label.png", png_bytes, content_type="image/png"),
        original_filename="label.png",
        content_type="image/png",
        image_format="png",
        size_bytes=len(png_bytes),
        width=64,
        height=64,
        checksum_sha256="0" * 64,
    )
    product_pk = product.pk

    product.delete()

    assert not ProductImage.objects.filter(product_id=product_pk).exists()


def test_deleting_the_uploader_keeps_the_image(db, product, png_bytes, media_root):
    """Evidence survives staff turnover.

    `SET_NULL`, not `CASCADE`: removing a user account must not silently delete
    the compliance evidence they collected.
    """
    user = get_user_model().objects.create_user(
        username="inspector", password="not-a-real-password"
    )
    image = ProductImage.objects.create(
        product=product,
        uploaded_by=user,
        image=SimpleUploadedFile("label.png", png_bytes, content_type="image/png"),
        original_filename="label.png",
        content_type="image/png",
        image_format="png",
        size_bytes=len(png_bytes),
        width=64,
        height=64,
        checksum_sha256="0" * 64,
    )

    user.delete()

    image.refresh_from_db()
    assert image.uploaded_by is None


# --- the panel a photograph shows -------------------------------------------


def test_view_type_records_which_panel_was_photographed(product_image):
    """An absent net quantity on a *front*-panel photo is not a missing declaration.

    The compliance engine needs to be able to tell the two apart; this column
    is where that fact lives. It defaults to `unspecified` rather than guessing
    a panel, because guessing would licence exactly the conclusion it exists to
    prevent.
    """
    assert ProductImage.ViewType.UNSPECIFIED in ProductImage.ViewType
    product_image.view_type = ProductImage.ViewType.PRINCIPAL_DISPLAY
    product_image.save()
    product_image.refresh_from_db()
    assert product_image.view_type == ProductImage.ViewType.PRINCIPAL_DISPLAY


@pytest.mark.parametrize("status", [s for s in ProductImage.Status])
def test_every_declared_lifecycle_status_is_storable(product_image, status):
    product_image.status = status
    product_image.save()
    product_image.refresh_from_db()
    assert product_image.status == status
