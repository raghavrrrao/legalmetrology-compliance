"""Image preparation: what it does, what it refuses, and what it cleans up.

Pillow is an optional extra, so these skip on an install without it rather than
failing. Everything they assert is about *our* handling - the transforms
applied, the guards enforced, the intermediates removed - never about Pillow's
own correctness.
"""

from pathlib import Path

import pytest

from labelextract.contracts import ImageRef
from labelextract.exceptions import (
    EngineNotAvailableError,
    ImageTooLargeError,
    InvalidImageError,
    PreprocessingError,
    UnsupportedImageFormatError,
)
from labelextract.preprocessing import PillowPreprocessor, PreprocessingConfig

PIL = pytest.importorskip("PIL", reason="Pillow is part of the optional [ocr] extra")

from PIL import Image  # noqa: E402  - imported after the skip guard on purpose


@pytest.fixture
def photo(tmp_path: Path):
    """Write a real image and return its `ImageRef`."""

    def _make(
        width: int = 120,
        height: int = 60,
        *,
        image_format: str = "png",
        exif_orientation: int | None = None,
        colour: tuple[int, int, int] = (200, 180, 160),
    ) -> ImageRef:
        path = tmp_path / f"label.{image_format}"
        image = Image.new("RGB", (width, height), colour)
        save_kwargs = {}
        if exif_orientation is not None:
            exif = image.getexif()
            exif[274] = exif_orientation  # 274 = Orientation
            save_kwargs["exif"] = exif
        image.save(path, format=image_format.upper(), **save_kwargs)
        return ImageRef(
            path=path,
            image_format=image_format,
            size_bytes=path.stat().st_size,
            width=width,
            height=height,
        )

    return _make


# --- the happy path ---------------------------------------------------------


def test_a_valid_image_is_prepared_without_touching_the_original(photo, tmp_path):
    """The original is the evidence a disputed finding is checked against."""
    source = photo()
    original_bytes = source.path.read_bytes()

    # The preprocessor is held for the length of the assertions on purpose:
    # it owns its intermediates and removes them when it is collected.
    preprocessor = PillowPreprocessor()
    processed = preprocessor.process(source)

    assert processed.path != source.path
    assert processed.path.exists()
    assert source.path.read_bytes() == original_bytes


def test_the_prepared_image_is_grayscale(photo):
    preprocessor = PillowPreprocessor()
    processed = preprocessor.process(photo())
    with Image.open(processed.path) as opened:
        assert opened.mode == "L"


def test_geometry_is_preserved_by_default(photo):
    """Defaults keep bounding boxes meaningful against the source image."""
    source = photo(width=120, height=60)
    processed = PillowPreprocessor().process(source)

    assert (processed.width, processed.height) == (120, 60)


def test_exif_rotation_is_applied(photo):
    """A phone photo arrives sideways unless the orientation tag is honoured.

    Tesseract reads pixels and ignores the tag, so without this the label is
    rotated 90 degrees and recognition collapses. This is the transform that
    justifies the whole preprocessing stage.
    """
    # Orientation 6 means "rotate 90 clockwise for display", so a landscape
    # frame becomes portrait once applied.
    source = photo(width=120, height=60, image_format="jpeg", exif_orientation=6)

    processed = PillowPreprocessor().process(source)

    assert (processed.width, processed.height) == (60, 120)


def test_rotation_can_be_switched_off(photo):
    config = PreprocessingConfig(apply_exif_orientation=False)
    source = photo(width=120, height=60, image_format="jpeg", exif_orientation=6)

    processed = PillowPreprocessor(config).process(source)

    assert (processed.width, processed.height) == (120, 60)


def test_downscaling_is_uniform_and_keeps_the_aspect_ratio(photo):
    config = PreprocessingConfig(max_dimension=60)
    processed = PillowPreprocessor(config).process(photo(width=120, height=60))

    assert (processed.width, processed.height) == (60, 30)


def test_upscaling_is_available_for_small_images(photo):
    config = PreprocessingConfig(min_dimension=240)
    processed = PillowPreprocessor(config).process(photo(width=120, height=60))

    assert (processed.width, processed.height) == (240, 120)


# --- refusals ---------------------------------------------------------------


def test_a_missing_file_is_rejected(tmp_path):
    ref = ImageRef(path=tmp_path / "gone.png", image_format="png", size_bytes=10)
    with pytest.raises(InvalidImageError):
        PillowPreprocessor().process(ref)


def test_an_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.png"
    path.write_bytes(b"")
    ref = ImageRef(path=path, image_format="png", size_bytes=0)

    with pytest.raises(InvalidImageError):
        PillowPreprocessor().process(ref)


def test_a_directory_is_rejected(tmp_path):
    ref = ImageRef(path=tmp_path, image_format="png", size_bytes=10)
    with pytest.raises(InvalidImageError):
        PillowPreprocessor().process(ref)


def test_a_file_that_is_not_an_image_is_rejected(tmp_path):
    """A renamed executable clears every check that asks the uploader."""
    path = tmp_path / "shell.png"
    path.write_bytes(b"#!/bin/sh\necho not an image\n")
    ref = ImageRef(path=path, image_format="png", size_bytes=path.stat().st_size)

    with pytest.raises(InvalidImageError):
        PillowPreprocessor().process(ref)


def test_an_oversized_file_is_rejected_before_it_is_decoded(photo):
    source = photo()
    config = PreprocessingConfig(max_bytes=10)

    with pytest.raises(ImageTooLargeError):
        PillowPreprocessor(config).process(source)


def test_a_decompression_bomb_is_rejected_on_its_declared_dimensions(photo):
    """The pixel budget is checked from the header, before pixels are loaded."""
    source = photo(width=120, height=60)
    config = PreprocessingConfig(max_pixels=100)

    with pytest.raises(ImageTooLargeError):
        PillowPreprocessor(config).process(source)


def test_an_unsupported_declared_format_is_rejected(photo, tmp_path):
    source = photo()
    mislabelled = ImageRef(
        path=source.path,
        image_format="tiff",
        size_bytes=source.size_bytes,
        width=source.width,
        height=source.height,
    )

    with pytest.raises(UnsupportedImageFormatError):
        PillowPreprocessor().process(mislabelled)


def test_a_missing_pillow_is_reported_as_an_unavailable_engine(monkeypatch, photo):
    """An optional dependency must produce a recorded failed run, not a 500."""
    import builtins

    real_import = builtins.__import__

    def refuse_pil(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no Pillow here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_pil)

    with pytest.raises(EngineNotAvailableError):
        PillowPreprocessor().process(photo())


# --- configuration ----------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"autocontrast_cutoff_percent": 60},
        {"max_dimension": 0},
        {"min_dimension": -1},
        {"min_dimension": 500, "max_dimension": 100},
        {"max_bytes": 0},
        {"max_pixels": 0},
    ],
)
def test_impossible_configuration_is_rejected_at_construction(kwargs):
    with pytest.raises(ValueError):
        PreprocessingConfig(**kwargs)


# --- cleanup ----------------------------------------------------------------


def test_release_deletes_the_intermediate(photo):
    preprocessor = PillowPreprocessor()
    processed = preprocessor.process(photo())
    assert processed.path.exists()

    preprocessor.release(processed)

    assert not processed.path.exists()


def test_release_is_safe_to_call_twice(photo):
    """It must never raise: losing a result over a temp file would be worse."""
    preprocessor = PillowPreprocessor()
    processed = preprocessor.process(photo())

    preprocessor.release(processed)
    preprocessor.release(processed)


def test_release_refuses_to_delete_a_path_it_does_not_own(photo, tmp_path):
    """Otherwise a caller could hand it an arbitrary path and have it removed."""
    preprocessor = PillowPreprocessor()
    preprocessor.process(photo())  # establishes the owned directory

    outsider = tmp_path / "not-ours.png"
    outsider.write_bytes(b"important")

    preprocessor.release(
        ImageRef(path=outsider, image_format="png", size_bytes=9)
    )

    assert outsider.exists()


def test_intermediates_land_in_an_explicit_directory_when_one_is_given(
    photo, tmp_path
):
    output = tmp_path / "prepared"
    preprocessor = PillowPreprocessor(output_dir=output)

    processed = preprocessor.process(photo())

    assert processed.path.parent == output


def test_concurrent_runs_do_not_collide(photo, tmp_path):
    preprocessor = PillowPreprocessor(output_dir=tmp_path / "prepared")
    first = preprocessor.process(photo())
    second = preprocessor.process(photo())

    assert first.path != second.path
    assert first.path.exists() and second.path.exists()


# --- a broken disk is not a broken image ------------------------------------


def test_a_failed_write_is_a_preprocessing_error_not_an_invalid_image(
    photo, monkeypatch
):
    """A full disk must not be reported as the user's photograph being bad.

    Reading and writing fail for opposite reasons - one is a fact about the
    uploaded file, the other about our own storage - and they carry different
    error codes because they send whoever reads them to different places. An
    earlier version wrapped the save in the same `except OSError` as the
    decode, so `No space left on device` reached the user as "the image could
    not be decoded: retake the photograph".
    """

    # Built before the patch: the fixture writes the source image with the
    # same `save` this test is about to break.
    source = photo()

    def full_disk(self, *args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Image.Image, "save", full_disk)

    with pytest.raises(PreprocessingError):
        PillowPreprocessor().process(source)


def test_a_write_that_leaves_no_file_is_a_preprocessing_error(photo, monkeypatch):
    """`destination.stat()` is inside the same guard as the save.

    A save that appears to succeed and leaves nothing behind is still a storage
    failure. Returning an `ImageRef` to a file that is not there would surface
    two stages later as "image does not exist" from OCR, pointing at the wrong
    component entirely.
    """

    source = photo()

    def save_nothing(self, *args, **kwargs):
        return None

    monkeypatch.setattr(Image.Image, "save", save_nothing)

    with pytest.raises(PreprocessingError):
        PillowPreprocessor().process(source)


def test_an_unwritable_output_directory_is_a_preprocessing_error(photo, tmp_path):
    """Creating the output directory is a storage concern too."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_bytes(b"this is a file, so nothing can be created inside it")

    preprocessor = PillowPreprocessor(output_dir=blocker / "prepared")

    with pytest.raises(PreprocessingError):
        preprocessor.process(photo())


def test_a_decode_failure_is_still_an_invalid_image(tmp_path):
    """The contrast: this one really is a fact about the input file."""
    path = tmp_path / "truncated.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    ref = ImageRef(path=path, image_format="png", size_bytes=path.stat().st_size)

    with pytest.raises(InvalidImageError):
        PillowPreprocessor().process(ref)


# --- the declared format and the decoded format must agree ------------------


def test_a_matching_declaration_is_accepted(photo):
    """The ordinary case: the caller's record of the file is correct."""
    preprocessor = PillowPreprocessor()
    processed = preprocessor.process(photo(image_format="png"))

    assert processed.path.exists()


def test_jpg_and_jpeg_are_the_same_declaration(photo, tmp_path):
    """Two spellings of one format must not read as a mismatch."""
    source = photo(image_format="jpeg")
    as_jpg = ImageRef(
        path=source.path,
        image_format="jpg",
        size_bytes=source.size_bytes,
        width=source.width,
        height=source.height,
    )

    preprocessor = PillowPreprocessor()
    assert preprocessor.process(as_jpg).path.exists()


def test_a_declared_format_that_contradicts_the_bytes_is_rejected(photo):
    """Declared WebP, decodes as PNG.

    Both formats are individually supported, which is exactly why checking each
    side against the allowlist separately let this through. The disagreement
    means the caller's record of the file is wrong, and everything derived from
    that record - the stored `image_format`, the API response, what a reviewer
    is shown - is wrong with it.
    """
    source = photo(image_format="png")
    mislabelled = ImageRef(
        path=source.path,
        image_format="webp",
        size_bytes=source.size_bytes,
        width=source.width,
        height=source.height,
    )

    with pytest.raises(UnsupportedImageFormatError) as raised:
        PillowPreprocessor().process(mislabelled)

    assert "mismatch" in str(raised.value).lower()


def test_a_declared_format_we_do_not_support_is_rejected(photo):
    source = photo(image_format="png")
    declared_tiff = ImageRef(
        path=source.path,
        image_format="tiff",
        size_bytes=source.size_bytes,
        width=source.width,
        height=source.height,
    )

    with pytest.raises(UnsupportedImageFormatError):
        PillowPreprocessor().process(declared_tiff)


def test_a_decoded_format_we_do_not_support_is_rejected(tmp_path):
    """The bytes are a real image, just not one of ours.

    The decoder's answer is authoritative, so a genuine BMP is refused however
    the caller labelled it - and the extension is never consulted.
    """
    path = tmp_path / "label.png"
    Image.new("RGB", (120, 60), (200, 180, 160)).save(path, format="BMP")
    ref = ImageRef(
        path=path,
        image_format="png",
        size_bytes=path.stat().st_size,
        width=120,
        height=60,
    )

    with pytest.raises(UnsupportedImageFormatError):
        PillowPreprocessor().process(ref)


# --- a failed write must not leave the intermediate behind -------------------


def test_a_file_written_before_a_later_failure_is_cleaned_up(
    photo, tmp_path, monkeypatch
):
    """`save()` succeeds, the next step does not.

    Nobody downstream ever receives this path, so nothing will call `release()`
    for it. Without the cleanup in `_write` it would sit in the output
    directory until the process exited - one leftover per failed upload.
    """
    source = photo()
    output = tmp_path / "prepared"
    preprocessor = PillowPreprocessor(output_dir=output)

    real_save = Image.Image.save

    def save_then_fail(self, destination, *args, **kwargs):
        real_save(self, destination, *args, **kwargs)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Image.Image, "save", save_then_fail)

    with pytest.raises(PreprocessingError):
        preprocessor.process(source)

    assert list(output.iterdir()) == []


def test_the_original_survives_a_failed_preprocessing_run(photo, tmp_path, monkeypatch):
    """Cleanup deletes our intermediate and never the user's evidence."""
    source = photo()
    original_bytes = source.path.read_bytes()
    preprocessor = PillowPreprocessor(output_dir=tmp_path / "prepared")

    real_save = Image.Image.save

    def save_then_fail(self, destination, *args, **kwargs):
        real_save(self, destination, *args, **kwargs)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Image.Image, "save", save_then_fail)

    with pytest.raises(PreprocessingError):
        preprocessor.process(source)

    assert source.path.exists()
    assert source.path.read_bytes() == original_bytes


def test_cleanup_does_not_swallow_the_failure_that_caused_it(
    photo, tmp_path, monkeypatch
):
    """The exception explaining *why* must survive the tidying up."""
    source = photo()
    preprocessor = PillowPreprocessor(output_dir=tmp_path / "prepared")

    real_save = Image.Image.save

    def save_then_fail(self, destination, *args, **kwargs):
        real_save(self, destination, *args, **kwargs)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Image.Image, "save", save_then_fail)

    with pytest.raises(PreprocessingError) as raised:
        preprocessor.process(source)

    assert isinstance(raised.value.__cause__, OSError)


def test_nothing_is_left_behind_when_the_write_never_starts(
    photo, tmp_path, monkeypatch
):
    """The other write failure: no file was created, so there is none to remove."""
    source = photo()
    output = tmp_path / "prepared"
    preprocessor = PillowPreprocessor(output_dir=output)

    def refuse(self, *args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(Image.Image, "save", refuse)

    with pytest.raises(PreprocessingError):
        preprocessor.process(source)

    assert list(output.iterdir()) == []


def test_releasing_the_same_intermediate_twice_is_harmless(photo, tmp_path):
    """Cleanup is idempotent, so the failure path and `release()` cannot clash."""
    preprocessor = PillowPreprocessor(output_dir=tmp_path / "prepared")
    processed = preprocessor.process(photo())

    preprocessor.release(processed)
    preprocessor.release(processed)

    assert not processed.path.exists()
