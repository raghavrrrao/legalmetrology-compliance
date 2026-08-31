"""Shared test fixtures for the backend.

Fixtures build real objects - real PNG bytes, real database rows - rather than
mocks, so the tests exercise the same code paths production does. The one thing
that is stubbed is the OCR engine, because there isn't one yet.
"""

import struct
import zlib

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog.models import Product, ProductCategory
from apps.extraction.models import ExtractedLabelField, ExtractionRun
from apps.images.models import ProductImage
from apps.rules.models import ComplianceRule


@pytest.fixture(autouse=True)
def _no_ssl_redirect_in_tests(settings):
    """Stop SecurityMiddleware redirecting the test client to HTTPS.

    `settings.SECURE_SSL_REDIRECT` is True whenever `DJANGO_DEBUG=False`, which
    is how CI runs (deliberately - CI should exercise a production-like
    configuration). Django's test client speaks plain HTTP unless every call
    passes `secure=True`, so SecurityMiddleware answers *every* request with
    `301 -> https://testserver/...` before it ever reaches a view. Locally,
    where `.env` sets `DJANGO_DEBUG=True`, the setting is never applied and the
    same tests pass - which is exactly how this reached CI unnoticed.

    Disabling it here rather than in the CI workflow keeps the suite correct in
    any environment, with DEBUG either way, instead of depending on a variable
    someone must remember to set. It removes an environment artefact, not
    coverage: the test client is not a browser and there is no TLS terminator
    in front of it, so the redirect can only ever mask the response under test.

    The production guarantee is not lost - it is asserted directly, and more
    precisely, in apps/core/tests/test_https_redirect.py.
    """
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture(autouse=True)
def _reset_api_throttles():
    """Give each test its own rate-limit budget.

    DRF's throttles count requests in Django's default cache, which is
    LocMemCache and therefore lives for the whole pytest session. Nothing
    empties it between tests, so every anonymous API request any test makes
    spends from one shared 30/min bucket - and the thirty-first fails with a
    429 no matter what it was actually asserting.

    That makes a test's result depend on how many API tests ran before it and
    on the order pytest chose, which is the suite reporting its own history
    rather than the code. It surfaced when the extraction endpoint's tests
    landed: they pass alone and turned five unrelated-looking assertions red in
    a full run.

    Cleared here rather than worked around per test, in the same spirit as the
    two fixtures either side of it: removing an environment artefact, not
    coverage. Throttling itself is still asserted - in
    `apps/core/tests/test_error_envelope.py`, against the exception, which is
    where the behaviour under test actually is.
    """
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _pin_runtime_configuration_in_tests(settings):
    """Pin the settings a developer's local `.env` would otherwise decide.

    `DEFAULT_EXTRACTION_ENGINE_NAME/VERSION` and `DEMO_PUBLIC_ANALYSIS_API` are
    read from the repository-root `.env`, which is git-ignored. That made the
    suite's result depend on an untracked file: several tests assert the
    default pipeline is a placeholder, and they passed only because every
    machine happened to have `null-engine` configured. Selecting the real
    Tesseract pipeline for a demonstration - a config change, touching no code
    - turned five of them red, which is the suite reporting the developer's
    environment rather than the code.

    Pinned here, in the same spirit as `_no_ssl_redirect_in_tests` above:
    removing an environment artefact rather than coverage. A test that cares
    about a different engine says so with `settings` or by passing
    `engine_name` explicitly, which several already do. Nothing is hidden -
    that a real engine can be configured is exercised by
    `apps/extraction/tests/test_extraction_service_ocr.py`, and the demo
    permission switch is asserted in both positions in
    `apps/compliance/tests/test_analysis_api.py`.
    """
    settings.DEFAULT_EXTRACTION_ENGINE_NAME = "null-engine"
    settings.DEFAULT_EXTRACTION_ENGINE_VERSION = "0.1.0"
    # Deny-by-default is the shipped behaviour; a demo flag left on in a local
    # .env must not silently satisfy a permission assertion.
    settings.DEMO_PUBLIC_ANALYSIS_API = False


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
