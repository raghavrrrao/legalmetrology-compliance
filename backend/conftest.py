"""Shared test fixtures for the backend.

Fixtures build real objects - real PNG bytes, real database rows - rather than
mocks, so the tests exercise the same code paths production does. The one thing
that is stubbed is the OCR engine, because there isn't one yet.
"""

import struct
import zlib

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog.models import Product, ProductCategory
from apps.extraction.models import ExtractedLabelField, ExtractionRun
from apps.images.models import ProductImage
from apps.rules.models import ComplianceRule


def make_png_bytes(width: int = 64, height: int = 64) -> bytes:
    """Build a genuinely decodable single-colour PNG.

    Written by hand rather than with Pillow so that a test asserting "Pillow
    accepts this" is not circular - the bytes are constructed independently of
    the library that validates them.
    """

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    # Bit depth 8, colour type 2 (truecolour), no interlace.
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def png_bytes() -> bytes:
    return make_png_bytes()


@pytest.fixture
def png_upload(png_bytes: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile("label.png", png_bytes, content_type="image/png")


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="tester", password="not-a-real-password"
    )


@pytest.fixture
def category(db) -> ProductCategory:
    return ProductCategory.objects.create(code="packaged-food", name="Packaged food")


@pytest.fixture
def product(db, category) -> Product:
    return Product.objects.create(name="Test biscuits", category=category)


@pytest.fixture
def media_root(settings, tmp_path):
    """Redirect uploads to a temp directory so tests never touch backend/media."""
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


@pytest.fixture
def product_image(db, product, png_bytes, media_root) -> ProductImage:
    """A stored image row whose file genuinely exists on disk."""
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


@pytest.fixture
def completed_run(db, product_image) -> ExtractionRun:
    """An extraction run that read text successfully but found no declarations.

    This is the state that distinguishes "we read the label and the declaration
    is absent" from "we could not read the label at all".
    """
    return ExtractionRun.objects.create(
        image=product_image,
        engine_name="stub",
        engine_version="0.0.0",
        status=ExtractionRun.Status.COMPLETED,
        recognised_text="Some text that was read from the package",
    )


@pytest.fixture
def empty_run(db, product_image) -> ExtractionRun:
    """An extraction run that recognised nothing - an unreadable photograph."""
    return ExtractionRun.objects.create(
        image=product_image,
        engine_name="stub",
        engine_version="0.0.0",
        status=ExtractionRun.Status.EMPTY,
        recognised_text="",
    )


@pytest.fixture
def make_rule(db, category):
    """Factory for rules. Defaults to verified, so a test opts in to unverified."""

    def _make(
        code: str = "TEST-0001",
        *,
        field_key: str = "net_quantity",
        verified: bool = True,
        categories=None,
        **kwargs,
    ) -> ComplianceRule:
        rule = ComplianceRule.objects.create(
            code=code,
            title=kwargs.pop("title", f"Test rule {code}"),
            requirement=kwargs.pop("requirement", "A test requirement."),
            source_status=(
                ComplianceRule.SourceStatus.VERIFIED
                if verified
                else ComplianceRule.SourceStatus.UNVERIFIED
            ),
            source_note="Fixture rule for tests." if verified else "",
            check_type=kwargs.pop("check_type", "field_presence"),
            parameters=kwargs.pop("parameters", {"field_key": field_key}),
            **kwargs,
        )
        rule.applies_to_categories.set(
            categories if categories is not None else [category]
        )
        return rule

    return _make


@pytest.fixture
def make_extracted_field(db):
    def _make(run: ExtractionRun, field_key: str, raw_value: str = "500 g", **kwargs):
        return ExtractedLabelField.objects.create(
            run=run, field_key=field_key, raw_value=raw_value, **kwargs
        )

    return _make
